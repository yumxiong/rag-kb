import assert from "node:assert/strict"
import { afterEach, test } from "node:test"
import { ApiError, ask, createSessionClient, getQuota, limitQuestion, quotaSchema } from "../lib/api"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const sessionResponse = () => Response.json({ transport: "cookie", expires_at: "2026-11-01T00:00:00Z", request_id: "test" })
const failure = (code: string, status: number) => Response.json({ detail: { code, message: "test", request_id: "error-test" } }, { status })

test("concurrent initialization and remounts reuse a single cookie request", async () => {
  let calls = 0
  globalThis.fetch = async (url, options) => {
    calls++
    assert.equal(url, "/api/session/anonymous")
    assert.equal(options?.credentials, "same-origin")
    assert.equal(options?.body, JSON.stringify({ transport: "cookie" }))
    return sessionResponse()
  }
  const client = createSessionClient()
  await Promise.all([client.initialize(), client.initialize(), client.initialize()])
  assert.equal(calls, 1)
})

test("expired startup allows only one extra request and latches failures", async () => {
  let calls = 0
  globalThis.fetch = async () => { calls++; return failure("anonymous_session_expired", 401) }
  const client = createSessionClient()
  await assert.rejects(client.initialize())
  await assert.rejects(client.initialize())
  assert.equal(calls, 2)
})

test("expired startup waits for deletion response then successfully reconnects", async () => {
  let calls = 0
  globalThis.fetch = async () => ++calls === 1 ? failure("anonymous_session_expired", 401) : sessionResponse()
  await createSessionClient().initialize()
  assert.equal(calls, 2)
})

test("invalid startup requires explicit reconnect and never auto recreates", async () => {
  let calls = 0
  globalThis.fetch = async () => ++calls === 1 ? failure("anonymous_session_invalid", 401) : sessionResponse()
  const client = createSessionClient()
  await assert.rejects(client.initialize())
  await assert.rejects(client.initialize())
  assert.equal(calls, 1)
  await client.reconnect()
  assert.equal(calls, 2)
})

test("concurrent identity recovery shares one promise and never replays ask", async () => {
  const paths: string[] = []
  globalThis.fetch = async (url) => { paths.push(String(url)); return url === "/api/qa/ask" ? failure("anonymous_session_required", 401) : sessionResponse() }
  const client = createSessionClient()
  await client.initialize()
  let caught: ApiError | undefined
  try { await ask("问题") } catch (error) { caught = error as ApiError }
  assert.ok(caught)
  await Promise.all([client.recover(caught), client.recover(caught)])
  assert.equal(paths.filter((path) => path === "/api/qa/ask").length, 1)
  assert.equal(paths.filter((path) => path === "/api/session/anonymous").length, 2)
})

test("network failure is one POST, not an automatic retry", async () => {
  let calls = 0
  globalThis.fetch = async () => { calls++; throw new TypeError("offline") }
  await assert.rejects(ask("问题"), (error: ApiError) => error.code === "network_error")
  assert.equal(calls, 1)
})

for (const [status, code] of [[429, "quota_exceeded"], [429, "rate_limited"], [503, "global_budget_exceeded"], [503, "service_busy"], [504, "upstream_timeout"], [502, "upstream_error"], [400, "invalid_request"], [503, "quota_storage_unavailable"], [503, "knowledge_base_unavailable"]] as const) {
  test(`structured ${status} ${code} retains request id`, async () => {
    globalThis.fetch = async () => failure(code, status)
    await assert.rejects(ask("问题"), (error: ApiError) => error.code === code && error.status === status && error.requestId === "error-test")
  })
}

test("HTML and malformed success bodies never become answers", async () => {
  globalThis.fetch = async () => new Response("<h1>gateway</h1>", { status: 502, headers: { "Content-Type": "text/html", "X-Request-ID": "gateway" } })
  await assert.rejects(ask("问题"), (error: ApiError) => error.code === "invalid_response" && error.requestId === "gateway")
  globalThis.fetch = async () => Response.json({ answer: "incomplete" })
  await assert.rejects(ask("问题"), (error: ApiError) => error.code === "invalid_response")
})

test("nullable quota is preserved without fake numeric limits", async () => {
  const value = { quota_enabled: true, has_custom_key: true, used_count: 2, daily_limit: null, remaining: null, reset_at: "2026-10-08T00:00:00Z", global_budget: { status: "exhausted", reset_at: "2026-10-08T00:00:00Z" }, request_id: "quota" }
  globalThis.fetch = async () => Response.json(value)
  assert.deepEqual(await getQuota(), value)
  assert.equal(quotaSchema.safeParse({ ...value, remaining: "unlimited" }).success, false)
})

test("2000 Unicode characters preserve Chinese and astral characters", () => {
  assert.equal(Array.from(limitQuestion("中😀".repeat(1100))).length, 2000)
  assert.equal(limitQuestion("中😀".repeat(1100)), "中😀".repeat(1000))
})
