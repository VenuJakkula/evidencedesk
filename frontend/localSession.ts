import type { Plugin } from 'vite'

/** Development-only same-origin bridge. Ordinary /api/local routes remain blocked. */
export function localSessionPlugin(target: string): Plugin {
  return {
    name: 'evidencedesk-local-session',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.url?.split('?')[0] !== '/dev/session-key') return next()
        const reply = (status: number, body: unknown) => {
          res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Pragma': 'no-cache' })
          res.end(JSON.stringify(body))
        }
        const peer = req.socket.remoteAddress
        const local = peer === '127.0.0.1' || peer === '::1' || peer === '::ffff:127.0.0.1'
        let localHost = false
        try { localHost = ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(`http://${req.headers.host}`).hostname) } catch { /* invalid host */ }
        if (req.method !== 'POST') return reply(405, { error: { code: 'method_not_allowed', message: 'Use POST for local connection.' } })
        if (!local || !localHost || req.headers.origin !== `http://${req.headers.host}` || req.headers['x-local-session'] !== 'true' ||
            (req.headers['sec-fetch-site'] && req.headers['sec-fetch-site'] !== 'same-origin') ||
            ['forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto'].some((header) => header in req.headers)) {
          return reply(403, { error: { code: 'local_connection_only', message: 'Automatic connection requires this local frontend origin.' } })
        }
        try {
          const upstream = new URL(target)
          if (!['127.0.0.1', 'localhost', '[::1]'].includes(upstream.hostname)) {
            return reply(403, { error: { code: 'local_backend_only', message: 'Automatic connection requires a loopback backend.' } })
          }
          // Intentionally a new direct request: no incoming proxy/cookie/auth headers forwarded.
          const response = await fetch(new URL('/local/session-key', upstream), {
            method: 'POST', headers: { 'X-Local-Session': 'true' }, redirect: 'error', signal: AbortSignal.timeout(10000),
          })
          if (!response.ok) {
            return reply(response.status, { error: { code: 'local_connection_unavailable', message: response.status === 404 ? 'Enable EVIDENCEDESK_ALLOW_LOCAL_FRONTEND=1 on the backend, then restart it.' : 'The backend did not allow automatic local connection.' } })
          }
          const body = await response.json() as { api_key?: unknown }
          if (typeof body.api_key !== 'string' || !body.api_key) throw new Error('Invalid bootstrap response')
          return reply(200, { api_key: body.api_key })
        } catch {
          return reply(503, { error: { code: 'backend_unavailable', message: 'Start the local backend and try connecting again.' } })
        }
      })
    },
  }
}
