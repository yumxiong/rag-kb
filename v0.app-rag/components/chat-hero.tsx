"use client"

import { useRef, useState } from "react"
import { ArrowUp, FileText, Loader2, Sparkles } from "lucide-react"
import { Answer, ApiError, limitQuestion } from "@/lib/api"
import { Button } from "@/components/ui/button"

export interface Message { question: string; answer?: Answer; error?: ApiError }
interface Props { inputValue: string; setInputValue: (value: string) => void; suggestions: string[]; messages: Message[]; pending: boolean; disabled: boolean; documentCount?: number; onQuestionClick: (question: string) => void; onSubmit: () => void }

export function ChatHero({ inputValue, setInputValue, suggestions, messages, pending, disabled, documentCount, onQuestionClick, onSubmit }: Props) {
  const composing = useRef(false)
  const [isComposing, setIsComposing] = useState(false)
  return <div className="flex-1 flex flex-col items-center px-4 py-8">
    <div className="w-full max-w-3xl mx-auto flex flex-col items-center">
      <div className="w-12 h-12 mb-4 rounded-2xl bg-accent flex items-center justify-center"><FileText className="w-6 h-6 text-accent-foreground" /></div>
      <h1 className="text-3xl md:text-4xl font-semibold mb-3 text-center">知问 · 智能文档问答</h1>
      <p className="text-muted-foreground text-center mb-6">{documentCount === undefined ? "正在读取知识库信息…" : `基于 ${documentCount} 个文档进行检索与问答`}</p>
      <div aria-label="当前对话" className="w-full space-y-4 mb-6">{messages.map((message, index) => <article key={index} className="rounded-xl border bg-card p-4 break-words">
        <h2 className="font-medium whitespace-pre-wrap">{message.question}</h2>
        {message.answer && <><p className="mt-3 whitespace-pre-wrap">{message.answer.answer}</p><div className="mt-4 space-y-2">{message.answer.sources.map((source, sourceIndex) => <details key={sourceIndex} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">引用 {sourceIndex + 1} · {source.document_name}{source.page_number != null ? ` · 第 ${source.page_number} 页` : ""}</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs font-sans text-muted-foreground">{source.content}</pre></details>)}</div><p className="mt-3 text-xs text-muted-foreground break-all">{message.answer.from_cache ? "缓存回答 · " : ""}请求编号：{message.answer.request_id}</p></>}
        {message.error && <p className="mt-3 text-sm">{message.error.message}</p>}
        {!message.answer && !message.error && <p role="status" className="mt-3 text-sm">正在检索并生成回答…</p>}
      </article>)}</div>
      <div className="w-full mb-8"><div className="relative bg-card border rounded-2xl shadow-lg overflow-hidden focus-within:ring-2 focus-within:ring-ring">
        <textarea aria-label="问题" value={inputValue} disabled={pending} onChange={(event) => setInputValue(composing.current ? event.target.value : limitQuestion(event.target.value))} onCompositionStart={() => { composing.current = true; setIsComposing(true) }} onCompositionEnd={(event) => { composing.current = false; setIsComposing(false); setInputValue(limitQuestion(event.currentTarget.value)) }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); if (!disabled && inputValue.trim()) onSubmit() } }} placeholder="输入你的问题" className="w-full bg-transparent px-5 py-4 pr-14 resize-none focus:outline-none min-h-[80px]" rows={2} />
        <Button aria-label="提交问题" onClick={onSubmit} disabled={disabled || isComposing || !inputValue.trim()} size="icon" className="absolute right-3 bottom-3 rounded-xl">{pending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}</Button>
      </div><p className="text-xs text-muted-foreground mt-2 text-center">{Array.from(inputValue).length}/2000 字符 · Shift+Enter 换行</p><p className="text-xs text-muted-foreground mt-2 text-center">新对话仅清空页面记录。每次提问独立检索，不发送历史对话。</p></div>
      {suggestions.length > 0 && <div className="w-full"><div className="flex items-center gap-2 justify-center mb-4"><Sparkles className="w-4 h-4 text-accent" /><span className="text-sm text-muted-foreground">试试这些问题</span></div><div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{suggestions.map((question) => <button key={question} disabled={disabled} onClick={() => onQuestionClick(question)} className="px-4 py-3 bg-card border rounded-xl text-sm text-left hover:bg-secondary disabled:opacity-50">{question}</button>)}</div></div>}
      <p className="mt-12 text-xs text-muted-foreground">知问 · RAG Demo</p>
    </div>
  </div>
}
