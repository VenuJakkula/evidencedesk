import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('workspace connection', () => {
  it('automatically obtains a local key on mount and verifies it without typing', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response({ api_key: 'automatic-test-key' }))
      .mockResolvedValueOnce(response({ status: 'ok' }))
      .mockResolvedValueOnce(response({ tenant: 'automatic', mode: 'extractive-baseline', authentication: 'local-api-key' }))
      .mockResolvedValueOnce(response({ items: [], total: 0, next_offset: null }))
    vi.stubGlobal('fetch', fetcher)
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('Your workspace is connected')
    expect(fetcher.mock.calls[0][0]).toBe('/dev/session-key')
    expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('X-API-Key')).toBe('automatic-test-key')
    expect(storage).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Disconnect and clear key' }))
    expect(screen.queryByText('automatic')).toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('offers retry and manual fallback when automatic connection is disabled', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(response({ error: { code: 'local_connection_unavailable', message: 'Enable local frontend connection.' } }, 404)))
    render(<App />)
    await screen.findByRole('alert')
    expect(screen.getByRole('alert').textContent).toContain('Enable local frontend connection.')
    expect(screen.getByLabelText('API key')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Connect automatically' })).toBeTruthy()
  })

  it('connects only after authentication, clears the password and disconnects without persistence', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response({ status: 'ok' })).mockResolvedValueOnce(response({ tenant: 'synthetic', mode: 'extractive-baseline', authentication: 'local-api-key' }))
    vi.stubGlobal('fetch', fetcher)
    const local = vi.spyOn(Storage.prototype, 'setItem')
    const user = userEvent.setup()
    render(<App autoConnect={false} />)
    const key = screen.getByLabelText('API key') as HTMLInputElement
    expect(key.type).toBe('password')
    await user.type(key, 'synthetic-key')
    await user.click(screen.getByRole('button', { name: /Connect workspace/ }))
    await screen.findByText('Your workspace is connected')
    expect(key.value).toBe('')
    expect(screen.getByText('synthetic')).toBeTruthy()
    expect(local).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Disconnect and clear key' }))
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('')
    expect(screen.queryByText('synthetic')).toBeNull()
    expect(local).not.toHaveBeenCalled()
  })

  it('displays invalid-key errors without declaring a connected session', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValueOnce(response({ status: 'ok' })).mockResolvedValueOnce(response({ detail: 'Invalid API key' }, 401)))
    render(<App autoConnect={false} />)
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /Connect workspace/ }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert').textContent).toContain('Invalid API key')
    expect(screen.queryByText('Your workspace is connected')).toBeNull()
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('')
  })

  it('renders loading, permits cancellation and ignores a late response', async () => {
    let resolve!: (value: Response) => void
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done })).mockResolvedValueOnce(response({ tenant: 'late', mode: 'extractive-baseline', authentication: 'local-api-key' }))
    vi.stubGlobal('fetch', fetcher)
    render(<App autoConnect={false} />)
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'test' } })
    fireEvent.click(screen.getByRole('button', { name: /Connect workspace/ }))
    expect(screen.getByText('Checking connection…')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    resolve(response({ status: 'ok' }))
    await waitFor(() => expect(screen.queryByText('Your workspace is connected')).toBeNull())
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('requires connection before evidence entry and review', async () => {
    const fetcher = vi.fn<typeof fetch>()
    vi.stubGlobal('fetch', fetcher)
    const user = userEvent.setup()
    render(<App autoConnect={false} />)
    await user.click(screen.getByRole('button', { name: 'Evidence' }))
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Answers start with evidence')
    expect(screen.getByText('Connect to add evidence.')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Review' }))
    expect(screen.getByText('Connect to review answers.')).toBeTruthy()
    expect(fetcher).not.toHaveBeenCalled()
  })
})
