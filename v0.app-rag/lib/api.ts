import { z } from "zod"

const count = z.number().int().nonnegative()
const utc = z.string().datetime()
const sessionSchema = z.object({ transport: z.literal("cookie"), expires_at: utc, request_id: z.string() })
export const quotaSchema = z.object({
  quota_enabled: z.boolean(), has_custom_key: z.boolean(), used_count: count,
  daily_limit: count.nullable(), remaining: count.nullable(), reset_at: utc,
  global_budget: z.object({ status: z.enum(["available", "exhausted"]), reset_at: utc }),
  request_id: z.string(),
})
export const answerSchema = z.object({
  answer: z.string().min(1),
  sources: z.array(z.object({ document_name: z.string(), content: z.string(), similarity_score: z.number(), page_number: z.number().nullable().optional() })),
  processing_time: z.number(), from_cache: z.boolean(), request_id: z.string(),
})
export const librarySchema = z.object({
  documents: z.array(z.object({ filename: z.string(), file_type: z.string(), chunk_count: count })), total: count,
})
const suggestionsSchema = z.object({ suggestions: z.array(z.string()), document_count: count })
export type Quota = z.infer<typeof quotaSchema>
export type Answer = z.infer<typeof answerSchema>
export type Library = z.infer<typeof librarySchema>

const messages: Record<string, string> = {
  invalid_request: "请求参数不正确，请检查问题内容。",
  origin_not_allowed: "当前访问来源未获允许，请联系站点管理员。",
  anonymous_session_required: "需要连接匿名会话。",
  anonymous_session_expired: "会话已过期。",
  anonymous_session_invalid: "会话失效，请重新连接。",
  quota_exceeded: "今日免费提问次数已用完，请等待重置。",
  rate_limited: "请求过于频繁，请稍后再试。",
  global_budget_exceeded: "全站今日预算已用完，请等待重置。",
  service_busy: "服务繁忙，请稍后再试。超时后的任务可能仍在结束中。",
  upstream_timeout: "回答超时，可能已计入今日次数，请稍后主动重试。",
  upstream_error: "模型服务调用失败，可能已计入今日次数。",
  quota_storage_unavailable: "额度存储暂不可用，请稍后再试。",
  service_unavailable: "问答服务暂不可用，请稍后再试。",
  knowledge_base_unavailable: "知识库暂不可用，请稍后再试。",
  feature_disabled: "当前功能未开放。",
  internal_error: "服务发生异常，请稍后再试。",
  network_error: "网络连接失败，响应丢失不代表未扣额。请检查网络后主动重试。",
  client_timeout: "等待回答超过 75 秒，可能已计次数。请稍后主动重试。",
  invalid_response: "服务响应异常，请稍后再试。",
}

export class ApiError extends Error {
  constructor(public code: string, public status = 0, public requestId?: string, public retryAfter?: number) {
    super(messages[code] ?? "服务暂时异常，请稍后再试。")
  }
}
export function asApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("network_error")
}

/** One HTTP attempt only. Never replay an ask, including after identity recovery. */
export async function request<T>(path: string, schema: z.ZodType<T>, body?: object, timeout = 15000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(path, {
      method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined, signal: controller.signal,
    })
    const requestId = response.headers.get("X-Request-ID") ?? undefined
    if (!response.headers.get("Content-Type")?.includes("application/json")) throw new ApiError("invalid_response", response.status, requestId)
    let value: unknown
    try { value = await response.json() } catch { throw new ApiError("invalid_response", response.status, requestId) }
    if (!response.ok) {
      const parsed = z.object({ detail: z.object({ code: z.string(), message: z.string(), request_id: z.string(), retry_after_seconds: z.number().optional() }) }).safeParse(value)
      const detail = parsed.success ? parsed.data.detail : undefined
      const delay = Number(response.headers.get("Retry-After") ?? detail?.retry_after_seconds)
      throw new ApiError(detail?.code ?? "invalid_response", response.status, detail?.request_id ?? requestId, Number.isFinite(delay) && delay > 0 ? delay : undefined)
    }
    const parsed = schema.safeParse(value)
    if (!parsed.success) throw new ApiError("invalid_response", response.status, requestId)
    return parsed.data
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(controller.signal.aborted ? (timeout === 75000 ? "client_timeout" : "network_error") : "network_error")
  } finally { clearTimeout(timer) }
}

/** A rejected promise remains latched across remounts until an explicit action. */
export function createSessionClient() {
  let flight: Promise<unknown> | undefined
  let ready = false
  const connect = (allowExpiredRetry: boolean): Promise<unknown> => {
    if (flight) return flight
    flight = (async () => {
      try {
        try { await request("/api/session/anonymous", sessionSchema, { transport: "cookie" }) }
        catch (error) {
          if (!allowExpiredRetry || !(error instanceof ApiError) || error.status !== 401 || error.code !== "anonymous_session_expired") throw error
          // The first response has completed; the browser has applied deletion.
          await request("/api/session/anonymous", sessionSchema, { transport: "cookie" })
        }
        ready = true
      } catch (error) { ready = false; throw error }
    })()
    return flight
  }
  return {
    initialize: () => connect(true),
    reconnect: () => { if (!ready) flight = undefined; return connect(false) },
    async recover(error: ApiError): Promise<boolean> {
      if (error.status !== 401) return false
      if (error.code === "anonymous_session_invalid") {
        ready = false
        flight = Promise.reject(error)
        void flight.catch(() => {})
        return false
      }
      if (!["anonymous_session_required", "anonymous_session_expired"].includes(error.code)) return false
      if (ready) { ready = false; flight = undefined }
      await connect(false)
      return true
    },
  }
}
export const session = createSessionClient()
export const getQuota = () => request("/api/qa/quota", quotaSchema)
export const getLibrary = () => request("/api/documents/library", librarySchema)
export const getSuggestions = () => request("/api/qa/suggestions", suggestionsSchema)
export const ask = (question: string) => request("/api/qa/ask", answerSchema, { question, max_sources: 3 }, 75000)
export const limitQuestion = (value: string) => Array.from(value).slice(0, 2000).join("")
