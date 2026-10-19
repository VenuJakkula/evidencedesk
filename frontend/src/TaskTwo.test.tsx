import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiClient } from './api'
import { Dashboard, EvidenceEntry } from './TaskTwo'
afterEach(cleanup)
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
const row = { id: 'saved-id', filename: 'security.xlsx', total: 5, created_at: '2026-10-08T01:00:00Z', status: 'imported' }
it('loads pages and reopens persisted questionnaires after remount', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response({ items: [row], total: 21, next_offset: 20 }))
    .mockResolvedValueOnce(response(row)).mockResolvedValueOnce(response({ items: [row], total: 21, next_offset: null }))
    .mockResolvedValueOnce(response({ items: [row], total: 21, next_offset: 20 })).mockResolvedValueOnce(response(row))
  const client = new ApiClient('test', fetcher)
  const view = render(<Dashboard client={client} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Open security.xlsx' }))
  await screen.findByText('Saved questionnaire: saved-id')
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  await screen.findByText('Page 2')
  await waitFor(() => expect(fetcher.mock.calls[2][0]).toBe('/api/questionnaires?offset=20&limit=20'))
  view.unmount(); render(<Dashboard client={client} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Open security.xlsx' }))
  await screen.findByText('Saved questionnaire: saved-id')
})
it('shows list errors and supports refresh', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response({ detail: 'Try again' }, 503)).mockResolvedValueOnce(response({ items: [], total: 0, next_offset: null }))
  render(<Dashboard client={new ApiClient('test', fetcher)} />)
  expect((await screen.findByRole('alert')).textContent).toBe('Try again')
  fireEvent.click(screen.getByRole('button', { name: 'Refresh questionnaires' }))
  await screen.findByText(/No questionnaires on this page/)
})
it('validates whitespace and saves evidence with the existing contract', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ id: 'document-id' }))
  render(<EvidenceEntry client={new ApiClient('test', fetcher)} />)
  const fields = [['Title', '   '], ['Plain text', 'Synthetic encryption policy.'], ['Version', '1'], ['Expiry date', '2099-01-01']]
  for (const [label, value] of fields) fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Save evidence' }))
  await screen.findByRole('alert'); expect(fetcher).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Policy' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save evidence' }))
  expect((await screen.findByRole('status')).textContent).toContain('document-id')
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({ title: 'Policy', content: 'Synthetic encryption policy.', version: '1', valid_until: '2099-01-01' })
  expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('')
})
it('retains evidence on API failure', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ detail: 'Invalid date' }, 422))
  render(<EvidenceEntry client={new ApiClient('test', fetcher)} />)
  for (const [label, value] of [['Title', 'Policy'], ['Plain text', 'Policy text'], ['Version', '1'], ['Expiry date', '2099-01-01']]) fireEvent.change(screen.getByLabelText(label), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Save evidence' }))
  expect((await screen.findByRole('alert')).textContent).toBe('Invalid date')
  expect((screen.getByLabelText('Plain text') as HTMLTextAreaElement).value).toBe('Policy text')
})
