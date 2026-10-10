import type { Metadata } from 'next'
import './globals.css'


export const metadata: Metadata = {
  title: '知问 · 智能文档问答',
  description: '上传文档 · 精准检索 · AI 答疑 —— 一个轻量的 RAG 知识库 Demo',
  generator: 'v0.app',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased bg-background">
        {children}
      </body>
    </html>
  )
}
