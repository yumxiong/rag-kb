/** Run after a local build with the default loopback RAG_BACKEND_ORIGIN. */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { cp, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createFixture } from './gateway_fixture.mjs'

const root = fileURLToPath(new URL('../../../v0.app-rag/', import.meta.url))
const standalone = `${root}/.next/standalone`
const manifest = JSON.parse(await readFile(`${root}/.next/routes-manifest.json`, 'utf8'))
assert.equal(manifest.rewrites.afterFiles[0].destination, 'http://127.0.0.1:18000/api/:path*')
await cp(`${root}/public`, `${standalone}/public`, { recursive: true })
await cp(`${root}/.next/static`, `${standalone}/.next/static`, { recursive: true })
const fixture = createFixture()
fixture.listen(18000, '127.0.0.1')
await once(fixture, 'listening')
const env = Object.fromEntries(['SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'ComSpec'].filter(k => process.env[k]).map(k => [k, process.env[k]]))
const child = spawn(process.execPath, ['server.js'], {
  cwd: standalone,
  env: { ...env, NODE_ENV: 'production', NEXT_TELEMETRY_DISABLED: '1', HOSTNAME: '127.0.0.1', PORT: '13011' },
  stdio: 'ignore',
})
const closed = once(child, 'close')
const origin = 'http://127.0.0.1:13011'
try {
  let ready = false
  for (let i = 0; i < 60; i++) {
    if (child.exitCode !== null) throw new Error('Standalone server exited before readiness')
    try { ready = (await fetch(origin, { signal: AbortSignal.timeout(1000) })).ok } catch { /* readiness */ }
    if (ready) break
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  assert.ok(ready, 'Standalone server did not become ready')
  const html = await (await fetch(origin)).text()
  assert.ok(!html.includes('backend:8000'))
  const asset = html.match(/src="([^" ]+\.js[^" ]*)"/)[1]
  assert.equal((await fetch(new URL(asset, origin))).status, 200)
  assert.equal((await fetch(`${origin}/icon.svg`)).status, 200)
  const headers = { 'Content-Type': 'application/json', Origin: origin }
  const session = await fetch(`${origin}/api/session/anonymous`, { method: 'POST', headers, body: '{}' })
  assert.equal(session.status, 201)
  assert.match(session.headers.get('set-cookie'), /HttpOnly; Secure; SameSite=Lax; Path=\/api/)
  const ask = await fetch(`${origin}/api/qa/ask`, { method: 'POST', headers: { ...headers, Cookie: 'rag_anonymous=synthetic-only' }, body: '{}' })
  assert.deepEqual({ ...await ask.json(), forwardedFor: undefined, forwardedProto: undefined }, { cookieForwarded: true, origin, forwardedFor: undefined, forwardedProto: undefined })
  const failed = await fetch(`${origin}/api/qa/ask`, { method: 'POST', headers, body: '{"status":503}' })
  assert.equal(failed.status, 503)
  assert.equal((await failed.json()).detail.code, 'global_budget_exceeded')
  assert.equal((await (await fetch(`${origin}/api/__fixture/status`)).json()).asks, 2)
  console.log('PASS: standalone HTML, static assets, cookie/origin forwarding, structured errors, one upstream attempt per ask')
} finally {
  child.kill()
  await closed
  fixture.closeAllConnections()
  await new Promise(resolve => fixture.close(resolve))
}
