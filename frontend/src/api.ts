export interface Health { status: string; mode: string }
export interface Session { tenant: string; mode: string; authentication: string; subject?: string; issuer?: string; roles?: string[]; identity_verified?: boolean }
export interface Download { blob: Blob; filename: string; exportId?: string }

export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Credentials stay in this instance's private memory, never in browser storage. */
export class ApiClient {
  #key: string
  constructor(key = '', private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis), private readonly options: { oidc?: boolean; tenant?: string; onDenied?: () => void } = {}) {
    this.#key = key
  }
  disconnect() { this.#key = '' }

  private async request(path: string, init: RequestInit = {}, authenticated = true, prefix: '/api' | '/dev' = '/api'): Promise<Response> {
    if (!/^\/[A-Za-z0-9/-]+(?:\?[^#]*)?$/.test(path) || path.startsWith('//') || path.startsWith('/local')) {
      throw new ApiError('invalid_path', 'Use an ordinary relative API route.', 0)
    }
    if (authenticated && !this.#key) throw new ApiError('not_connected', 'Connect your workspace first.', 0)
    const headers = new Headers(init.headers)
    if (authenticated) {
      if (this.options.oidc) { headers.set('Authorization', `Bearer ${this.#key}`); headers.set('X-Tenant-ID', this.options.tenant || '') }
      else headers.set('X-API-Key', this.#key)
    }
    try {
      const response = await this.fetcher(`${prefix}${path}`, { ...init, headers, cache: 'no-store', credentials: 'omit', redirect: 'error' })
      if (!response.ok) {
        let code = `http_${response.status}`
        let message = response.status === 401 ? 'API key was not accepted. Check the key and try again.' : `The API could not complete the request (${response.status}).`
        try {
          const data: unknown = await response.json()
          if (data && typeof data === 'object') {
            const error = (data as { error?: { code?: unknown; message?: unknown } }).error
            const detail = (data as { detail?: unknown }).detail
            if (typeof error?.code === 'string') code = error.code
            if (typeof error?.message === 'string') message = error.message
            else if (typeof detail === 'string') message = detail
          }
        } catch { /* HTML proxy errors and empty bodies use the safe fallback. */ }
        if (this.options.oidc && [401,403].includes(response.status)) { this.disconnect(); this.options.onDenied?.() }
        throw new ApiError(code, message, response.status)
      }
      return response
    } catch (error) {
      if (error instanceof ApiError || (error && typeof error === 'object' && 'name' in error && error.name === 'AbortError')) throw error
      throw new ApiError('network_error', 'Cannot reach the API. Check that the backend is running, then try again.', 0)
    }
  }

  async json<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}, authenticated = true): Promise<T> {
    const response = await this.request(path, { method: options.method || 'GET', signal: options.signal,
      ...(options.body !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options.body) } : {}) }, authenticated)
    if (response.status === 204) return undefined as T
    try { return await response.json() as T }
    catch { throw new ApiError('invalid_response', 'The API returned an unexpected response.', response.status) }
  }

  async upload<T>(path: string, form: FormData, idempotencyKey?: string, signal?: AbortSignal): Promise<T> {
    const response = await this.request(path, { method: 'POST', body: form, signal,
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined })
    try { return await response.json() as T }
    catch { throw new ApiError('invalid_response', 'The API returned an unexpected response.', response.status) }
  }

  async download(path: string, method = 'POST', signal?: AbortSignal): Promise<Download> {
    const response = await this.request(path, { method, signal })
    const filename = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/i)?.[1] || 'questionnaire-export.zip'
    const exportId = response.headers.get('X-Export-ID')
    return { ...(exportId && /^[A-Za-z0-9-]{1,100}$/.test(exportId) ? { exportId } : {}), blob: await response.blob(), filename: filename.replace(/[^A-Za-z0-9_. -]/g, '_').replace(/^\.+/, '').slice(0, 150) || 'questionnaire-export.zip' }
  }

  async connect(signal?: AbortSignal): Promise<Session> {
    const health = await this.json<Health>('/health', { signal }, false)
    if (!health || typeof health !== 'object' || typeof health.status !== 'string') {
      throw new ApiError('invalid_response', 'The API returned an unexpected health response.', 0)
    }
    if (health.status !== 'ok') throw new ApiError('unhealthy', 'The API is not ready. Try again shortly.', 503)
    const session = await this.json<Session>('/session', { signal })
    if (!session || typeof session !== 'object' || typeof session.tenant !== 'string' || !session.tenant || typeof session.mode !== 'string' || session.authentication !== (this.options.oidc ? 'oidc' : 'local-api-key') || (this.options.oidc && (!session.identity_verified || !session.subject || !Array.isArray(session.roles)))) {
      throw new ApiError('invalid_response', 'The API returned an unexpected connection response.', 0)
    }
    return session
  }

  async autoConnect(signal?: AbortSignal): Promise<Session> {
    if (this.options.oidc) throw new ApiError('oidc_required', 'Provide an OIDC access token. Local key bootstrap is disabled.', 0)
    const response = await this.request('/session-key', { method: 'POST', signal, headers: { 'X-Local-Session': 'true' } }, false, '/dev')
    let data: { api_key?: unknown }
    try { data = await response.json() as { api_key?: unknown } }
    catch { throw new ApiError('invalid_response', 'The local connection response was invalid.', 0) }
    if (!data || typeof data.api_key !== 'string' || !data.api_key || data.api_key.length > 4096) {
      throw new ApiError('invalid_response', 'The local connection response was invalid.', 0)
    }
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    this.#key = data.api_key
    try { return await this.connect(signal) }
    catch (error) { this.disconnect(); throw error }
  }
}
