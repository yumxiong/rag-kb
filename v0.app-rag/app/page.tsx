"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Sidebar } from "@/components/sidebar"
import { ChatHero, Message } from "@/components/chat-hero"
import { ApiError, Library, Quota, asApiError, ask, getLibrary, getQuota, getSuggestions, session } from "@/lib/api"

export default function Home() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [inputValue, setInputValue] = useState("")
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [quota, setQuota] = useState<Quota | null>(null)
  const [library, setLibrary] = useState<Library | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [pending, setPending] = useState(false)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [info, setInfo] = useState("")
  const [lastQuestion, setLastQuestion] = useState("")
  const busy = useRef(false)
  const [waitingUntil, setWaitingUntil] = useState(0)
  const [waitSeconds, setWaitSeconds] = useState(0)

  const showError = useCallback((value: unknown) => {
    const failure = asApiError(value)
    setError(failure)
    if (failure.retryAfter) setWaitingUntil(Date.now() + failure.retryAfter * 1000)
    if (failure.status === 401) setReady(false)
  }, [])
  useEffect(() => {
    const tick = () => setWaitSeconds(Math.max(0, Math.ceil((waitingUntil - Date.now()) / 1000)))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [waitingUntil])

  const refreshQuota = useCallback(async () => {
    try { setQuota(await getQuota()) }
    catch (value) {
      const failure = asApiError(value)
      try {
        if (await session.recover(failure)) {
          setQuota(await getQuota()); setReady(true)
          setInfo("会话已恢复，额度已刷新。原问题未自动重发，请主动提交。")
        } else { setQuota(null); showError(failure) }
      } catch (recoveryError) { setQuota(null); setReady(false); showError(recoveryError) }
    }
  }, [showError])

  useEffect(() => {
    let active = true
    void session.initialize().then(async () => {
      if (active) { setReady(true); await refreshQuota() }
    }).catch((value) => { if (active) showError(value) })
    void Promise.allSettled([getSuggestions(), getLibrary()]).then(([questions, documents]) => {
      if (!active) return
      if (questions.status === "fulfilled") setSuggestions(questions.value.suggestions)
      else showError(questions.reason)
      if (documents.status === "fulfilled") setLibrary(documents.value)
      else showError(documents.reason)
    })
    return () => { active = false }
  }, [refreshQuota, showError])

  const submit = async (value: string) => {
    if (busy.current || !ready || waitSeconds || !value.trim() || Array.from(value).length > 2000) return
    busy.current = true; setPending(true); setError(null); setInfo(""); setLastQuestion("")
    const question = value.trim()
    setInputValue("")
    setMessages((current) => [...current, { question }])
    try {
      const answer = await ask(question)
      setMessages((current) => [...current.slice(0, -1), { question, answer }])
    } catch (value) {
      const failure = asApiError(value)
      setLastQuestion(question)
      setMessages((current) => [...current.slice(0, -1), { question, error: failure }])
      showError(failure)
      try {
        if (await session.recover(failure)) {
          setReady(true); setError(null)
          setInfo("会话已恢复。原问题未自动重发，请主动提交。")
        }
      } catch (recoveryError) { setReady(false); showError(recoveryError) }
    } finally {
      await refreshQuota()
      busy.current = false; setPending(false)
    }
  }

  const reconnect = async () => {
    if (busy.current || waitSeconds) return
    busy.current = true; setPending(true); setError(null)
    try { await session.reconnect(); setReady(true); await refreshQuota() }
    catch (value) { showError(value) }
    finally { busy.current = false; setPending(false) }
  }
  const unavailable = pending || !ready || waitSeconds > 0 || quota?.remaining === 0 || quota?.global_budget.status === "exhausted"
  return <div className="flex h-dvh overflow-hidden">
    <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen((open) => !open)} library={library} pending={pending} onNewChat={() => {
      if (busy.current) return
      setMessages([]); setInputValue(""); setLastQuestion(""); setInfo(""); setError(null); setSidebarOpen(false)
    }} />
    <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">
      <div className="max-w-3xl w-full mx-auto px-4 pt-16 lg:pt-5 space-y-3">
        {!ready && !error && <p role="status">正在连接匿名会话…</p>}
        {quota && <div className="rounded-xl border bg-card p-3 text-sm" aria-label="额度信息">
          <p>{quota.remaining === null ? "当前模式不执行个人次数上限" : `今日剩余 ${quota.remaining} / ${quota.daily_limit} 次`} · 默认 Key 已用 {quota.used_count} 次</p>
          <p className="text-xs text-muted-foreground">下次重置：{new Date(quota.reset_at).toLocaleString(undefined, { timeZoneName: "short" })}（每日 UTC 00:00）</p>
          {quota.global_budget.status === "exhausted" && <p role="alert">全站今日预算已用完。重置：{new Date(quota.global_budget.reset_at).toLocaleString()}</p>}
          {quota.remaining === 0 && <p role="alert">今日免费提问次数已用完，请等待重置。</p>}
        </div>}
        <button className="text-xs underline" disabled={pending || !ready || waitSeconds > 0} onClick={() => { setError(null); void refreshQuota() }}>刷新额度</button>
        {(!library || suggestions.length === 0) && <button className="ml-3 text-xs underline" disabled={pending || waitSeconds > 0} onClick={() => {
          setError(null)
          void Promise.all([getLibrary(), getSuggestions()]).then(([documents, questions]) => { setLibrary(documents); setSuggestions(questions.suggestions) }).catch(showError)
        }}>刷新知识库与示例</button>}
        {info && <p role="status" className="text-sm">{info}</p>}
        {error && <div role="alert" className="rounded-xl border border-destructive p-3 text-sm">
          <p>{error.message}</p>{error.requestId && <p className="break-all text-xs">请求编号：{error.requestId}</p>}
          {waitSeconds > 0 && <p>请等待 {waitSeconds} 秒后主动重试。</p>}
        </div>}
        {!ready && error && <button className="underline text-sm" disabled={pending || waitSeconds > 0} onClick={() => void reconnect()}>重新连接</button>}
        {lastQuestion && <div className="text-sm"><p>已受理请求即使失败也可能计入今日次数。重试会发起一次新的问答。</p><button className="underline" disabled={unavailable} onClick={() => void submit(lastQuestion)}>明确重试上个问题</button></div>}
      </div>
      <ChatHero inputValue={inputValue} setInputValue={setInputValue} suggestions={suggestions} messages={messages} pending={pending} disabled={unavailable} documentCount={library?.total} onQuestionClick={(question) => void submit(question)} onSubmit={() => void submit(inputValue)} />
    </main>
  </div>
}
