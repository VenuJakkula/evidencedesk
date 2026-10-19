import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { allowedApiPath } from './proxy.ts'
import { localSessionPlugin } from './localSession.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.EVIDENCEDESK_API_TARGET || 'http://127.0.0.1:8000'
  const upstream = new URL(target)
  if (!['http:', 'https:'].includes(upstream.protocol) || upstream.username || upstream.password || upstream.search || upstream.hash || upstream.pathname !== '/') {
    throw new Error('EVIDENCEDESK_API_TARGET must be an HTTP(S) origin without credentials or a path.')
  }
  return {
    plugins: [react(), localSessionPlugin(target)],
    server: {
      host: '127.0.0.1', port: 5173, strictPort: true, cors: false,
      proxy: {
        '/api': {
          target, changeOrigin: true, xfwd: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
          bypass: (req, res) => {
            if (!allowedApiPath(req.url || '')) {
              res?.writeHead(404, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
              res?.end(JSON.stringify({ error: { code: 'route_not_proxied', message: 'This route is unavailable through the frontend.' } }))
              return false
            }
          },
        },
      },
    },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true },
    test: { include: ['src/**/*.test.{ts,tsx}', 'proxy.test.ts'], environment: 'jsdom', maxWorkers: 2, restoreMocks: true, clearMocks: true },
  }
})
