/** Transport-only fixture. No real identity, admission, storage or provider. */
import http from 'node:http'
import { pathToFileURL } from 'node:url'

export function createFixture() {
  let asks = 0
  return http.createServer(async (req, res) => {
    let raw = ''
    for await (const chunk of req) raw += chunk
    const body = raw ? JSON.parse(raw) : {}
    const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Request-ID': 'synthetic-gateway' }
    if (req.url === '/api/session/anonymous') {
      res.writeHead(201, { ...headers, 'Set-Cookie': 'rag_anonymous=synthetic-only; HttpOnly; Secure; SameSite=Lax; Path=/api' })
      res.end(JSON.stringify({ transport: 'cookie', request_id: 'synthetic-gateway' }))
    } else if (req.url === '/api/qa/ask') {
      asks++
      if (body.mode === 'disconnect') { req.socket.destroy(); return }
      if (body.mode === 'timeout') { return }
      const status = body.status ?? 200
      const code = { 429: 'quota_exceeded', 503: 'global_budget_exceeded', 502: 'upstream_error', 504: 'upstream_timeout' }[status]
      res.writeHead(status, { ...headers, ...(status === 429 ? { 'Retry-After': '7' } : {}) })
      res.end(JSON.stringify(code ? { detail: { code, message: 'Synthetic fixture', request_id: 'synthetic-gateway', ...(status === 429 ? { retry_after_seconds: 7 } : {}) } } : {
        cookieForwarded: req.headers.cookie === 'rag_anonymous=synthetic-only',
        origin: req.headers.origin,
        forwardedFor: req.headers['x-forwarded-for'],
        forwardedProto: req.headers['x-forwarded-proto'],
      }))
    } else if (req.url === '/api/__fixture/status') {
      res.writeHead(200, headers)
      res.end(JSON.stringify({ asks }))
    } else {
      res.writeHead(404, headers)
      res.end('{}')
    }
  })
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  createFixture().listen(8000, '0.0.0.0')
}
