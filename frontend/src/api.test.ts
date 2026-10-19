import { describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './api'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const session = { tenant: 'test-tenant', mode: 'extractive-baseline', authentication: 'local-api-key' }

describe('API client', () => {
  it('acquires a development session key without proxying recovery or rotating it', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ api_key: 'local-test-key' }))
      .mockResolvedValueOnce(json({ status: 'ok' })).mockResolvedValueOnce(json(session))
    expect(await new ApiClient('', fetcher).autoConnect()).toEqual(session)
    expect(fetcher.mock.calls[0][0]).toBe('/dev/session-key')
    expect(fetcher.mock.calls[0][1]?.method).toBe('POST')
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('X-Local-Session')).toBe('true')
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has('X-API-Key')).toBe(false)
    expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('X-API-Key')).toBe('local-test-key')
  })

  it('does not authenticate malformed key issuance or retain a key after failed validation', async () => {
    const malformed = vi.fn<typeof fetch>().mockResolvedValue(json({ api_key: null }))
    await expect(new ApiClient('', malformed).autoConnect()).rejects.toMatchObject({ code: 'invalid_response' })
    expect(malformed).toHaveBeenCalledTimes(1)
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ api_key: 'test' })).mockResolvedValueOnce(json({ status: 'ok' })).mockResolvedValueOnce(json({ detail: 'Invalid API key' }, 401))
    const client = new ApiClient('', fetcher)
    await expect(client.autoConnect()).rejects.toMatchObject({ status: 401 })
    await expect(client.json('/session')).rejects.toMatchObject({ code: 'not_connected' })
  })

  it('checks public health then authenticates through a read-only session', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ status: 'ok', mode: 'extractive-baseline' })).mockResolvedValueOnce(json(session))
    const client = new ApiClient('test-key', fetcher)
    expect(await client.connect()).toEqual(session)
    expect(fetcher.mock.calls[0][0]).toBe('/api/health')
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).has('X-API-Key')).toBe(false)
    expect(fetcher.mock.calls[1][0]).toBe('/api/session')
    expect(new Headers(fetcher.mock.calls[1][1]?.headers).get('X-API-Key')).toBe('test-key')
    expect(fetcher.mock.calls[1][1]?.redirect).toBe('error')
    client.disconnect()
    await expect(client.json('/session')).rejects.toMatchObject({ code: 'not_connected' })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it.each([
    [{ detail: 'Invalid API key' }, 401, 'http_401', 'Invalid API key'],
    [{ error: { code: 'revision_conflict', message: 'Reload the current revision.' } }, 409, 'revision_conflict', 'Reload the current revision.'],
    [{ detail: [{ msg: 'invalid' }] }, 422, 'http_422', 'The API could not complete the request (422).'],
  ])('normalizes legacy and structured error bodies', async (body, status, code, message) => {
    const client = new ApiClient('test-key', vi.fn<typeof fetch>().mockResolvedValue(json(body, status)))
    await expect(client.json('/session')).rejects.toMatchObject({ code, message, status })
  })

  it('handles non-JSON proxy failures and network failures without leaking request details', async () => {
    const htmlClient = new ApiClient('test-key', vi.fn<typeof fetch>().mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502 })))
    await expect(htmlClient.json('/session')).rejects.toMatchObject({ code: 'http_502', status: 502 })
    const network = new ApiClient('test-key', vi.fn<typeof fetch>().mockRejectedValue(new Error('sensitive transport text')))
    await expect(network.json('/session')).rejects.toMatchObject({ code: 'network_error', message: 'Cannot reach the API. Check that the backend is running, then try again.' })
  })

  it('does not report a healthy public API as an authenticated connection', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ status: 'ok' })).mockResolvedValueOnce(json({ detail: 'Invalid API key' }, 401))
    await expect(new ApiClient('wrong', fetcher).connect()).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('rejects malformed successful connection data', async () => {
    for (const malformed of [null, { tenant: 'test' }]) {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ status: 'ok' })).mockResolvedValueOnce(json(malformed))
      await expect(new ApiClient('test', fetcher).connect()).rejects.toMatchObject({ code: 'invalid_response' })
    }
    await expect(new ApiClient('test', vi.fn<typeof fetch>().mockResolvedValue(json(null))).connect()).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('sends JSON and multipart bodies correctly, leaving multipart boundaries to the browser', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json({ id: 'doc' })).mockResolvedValueOnce(json({ total: 5 }))
    const client = new ApiClient('test-key', fetcher)
    await client.json('/documents', { method: 'POST', body: { title: 'Synthetic policy' } })
    expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('Content-Type')).toBe('application/json')
    const form = new FormData()
    form.append('file', new File(['synthetic'], 'sample.xlsx'))
    await client.upload('/questionnaires', form, 'retry-key')
    expect(fetcher.mock.calls[1][1]?.body).toBe(form)
    const headers = new Headers(fetcher.mock.calls[1][1]?.headers)
    expect(headers.has('Content-Type')).toBe(false)
    expect(headers.get('Idempotency-Key')).toBe('retry-key')
  })

  it('returns binary downloads with safe filenames', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('zip-bytes', { headers: { 'Content-Disposition': 'attachment; filename="../../result.zip"' } }))
    const output = await new ApiClient('test', fetcher).download('/questionnaires/id/export')
    expect(await output.blob.text()).toBe('zip-bytes')
    expect(output.filename).not.toMatch(/[\\/]/)
    expect(fetcher.mock.calls[0][1]?.method).toBe('POST')
  })

  it('blocks absolute URLs, path traversal and local recovery before sending a key', async () => {
    const fetcher = vi.fn<typeof fetch>()
    for (const path of ['https://evil.example/session', '//evil.example/session', '/local/api-key', '/questionnaires/../local/api-key', '/%2e%2e/local/api-key']) {
      await expect(new ApiClient('test', fetcher).json(path)).rejects.toMatchObject({ code: 'invalid_path' })
    }
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('preserves cancellation rather than reporting it as a network failure', async () => {
    const abort = new DOMException('Aborted', 'AbortError')
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(abort)
    await expect(new ApiClient('test', fetcher).json('/session')).rejects.toBe(abort)
  })
  it('reads an export receipt ID without allowing a header to become an arbitrary route', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('zip', { headers: { 'X-Export-ID': 'export-id' } }))
      .mockResolvedValueOnce(new Response('zip', { headers: { 'X-Export-ID': '../../local/api-key' } }))
    const client = new ApiClient('test', fetcher)
    expect((await client.download('/questionnaires/id/export')).exportId).toBe('export-id')
    expect((await client.download('/questionnaires/id/export')).exportId).toBeUndefined()
  })

})
