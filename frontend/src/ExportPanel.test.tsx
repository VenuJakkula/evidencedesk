import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ApiClient } from './api'
import { ExportPanel, type ExportSummary } from './ExportPanel'
afterEach(cleanup)
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
const summary = (): ExportSummary => ({ export_id: 'export-id', questionnaire_id: 'q', created_at: '2026-10-08T01:00:00Z', total: 22, selected_count: 1, unresolved_count: 21, offset: 0, limit: 20, next_offset: 20, details_available: true, items: [{ item_id: 'missing', question: 'Needs evidence?', sheet: 'Security', answer_cell: 'C6', owner: 'Evidence owner', reason: 'stale_evidence' }] })
function setup(fetcher: typeof fetch, overrides = {}) {
  const onDownload = vi.fn()
  render(<ExportPanel client={new ApiClient('test', fetcher)} questionnaireId="q" disabled={false} unsaved={false} recoveryRequired={false} receipt={{ exportId: 'export-id', filename: 'questionnaire-export.zip' }} error="" onDownload={onDownload} {...overrides} />)
  return onDownload
}
it('loads authoritative snapshot counts and paginated unresolved reasons without counting review selection', async () => {
  const page = summary()
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(page)).mockResolvedValueOnce(response({ ...page, offset: 20, next_offset: null }))
  setup(fetcher)
  await screen.findByText('1 answers applied · 21 unresolved · 22 total')
  expect(screen.getByText('Evidence missing, changed or expired')).toBeTruthy(); expect(screen.getByText('Security!C6')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Next unresolved items' }))
  await screen.findByText('Receipt page 2')
  expect(fetcher.mock.calls[1][0]).toBe('/api/questionnaires/q/exports/export-id?offset=20&limit=20')
  expect(screen.getByText(/Later edits and approvals do not change that file/)).toBeTruthy()
})
it('keeps download receipt failures separate and retries only metadata', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response({ error: { code: 'not_found', message: 'Receipt unavailable' } }, 404)).mockResolvedValueOnce(response(summary()))
  const onDownload = setup(fetcher)
  expect((await screen.findByRole('alert')).textContent).toContain('Bundle received, but its receipt could not load')
  fireEvent.click(screen.getByRole('button', { name: 'Reload export receipt' }))
  await screen.findByText('Last export result'); expect(onDownload).not.toHaveBeenCalled()
  expect(fetcher.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
})
it('blocks exporting unsaved edits or unresolved mutation recovery', () => {
  setup(vi.fn<typeof fetch>(), { receipt: null, unsaved: true, recoveryRequired: true })
  expect((screen.getByRole('button', { name: 'Download export bundle' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText(/Save or discard all unsaved edits/)).toBeTruthy()
  expect(screen.getByText(/Reload items with unresolved save or approval errors/)).toBeTruthy()
})
it('does not invent counts when a historical response has no receipt ID', () => {
  const fetcher = vi.fn<typeof fetch>()
  setup(fetcher, { receipt: { filename: 'old-export.zip' } })
  expect(screen.getByText(/Receipt metadata is unavailable/)).toBeTruthy(); expect(fetcher).not.toHaveBeenCalled()
  expect(screen.queryByText(/answers applied/)).toBeNull()
})
