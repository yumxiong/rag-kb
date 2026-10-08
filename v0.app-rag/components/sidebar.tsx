"use client"

import { ChevronLeft, FileText, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Library } from "@/lib/api"
import { cn } from "@/lib/utils"

interface Props { isOpen: boolean; onToggle: () => void; library: Library | null; pending: boolean; onNewChat: () => void }
export function Sidebar({ isOpen, onToggle, library, pending, onNewChat }: Props) {
  return <>
    {isOpen && <button aria-label="收起侧栏" className="fixed inset-0 bg-background/80 z-40 lg:hidden" onClick={onToggle} />}
    <aside aria-label="知识库侧栏" className={cn("shrink-0 z-50 h-full bg-sidebar border-r border-sidebar-border flex flex-col", isOpen ? "fixed lg:relative w-64" : "hidden lg:flex lg:w-16")}>
      <div className="flex items-center justify-between p-3 border-b border-sidebar-border">
        {isOpen && <div className="flex items-center gap-3"><FileText className="w-5 h-5 text-accent" /><span className="font-semibold text-sm">知问 · 知识库</span></div>}
        <Button variant="ghost" size="icon" onClick={onToggle} aria-label={isOpen ? "关闭侧栏" : "展开侧栏"} aria-expanded={isOpen}><ChevronLeft className={cn("w-4 h-4", !isOpen && "rotate-180")} /></Button>
      </div>
      <div className="p-2"><Button aria-label="新对话" disabled={pending} onClick={onNewChat} className="w-full gap-2 px-2 bg-secondary text-secondary-foreground"><Plus className="w-4 h-4" />{isOpen && <span>新对话</span>}</Button></div>
      {isOpen && <div className="px-4 py-3 overflow-y-auto"><h2 className="text-sm mb-3">知识库 {library ? `· ${library.total} 个文档` : "暂未加载"}</h2><ul className="space-y-3 text-xs text-muted-foreground">{library?.documents.map((document, index) => <li key={`${document.filename}-${index}`} className="break-words">{document.filename}<span className="block">{document.chunk_count} 个分块</span></li>)}</ul></div>}
    </aside>
    {!isOpen && <Button variant="ghost" size="icon" onClick={onToggle} aria-label="打开侧栏" className="fixed top-3 left-4 z-30 lg:hidden bg-card border"><ChevronLeft className="w-4 h-4 rotate-180" /></Button>}
  </>
}
