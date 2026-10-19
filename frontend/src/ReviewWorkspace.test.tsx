import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiClient } from './api'
import { ReviewWorkspace, type ReviewItem } from './ReviewWorkspace'
import { startZipDownload } from './download'
vi.mock('./download', () => ({ startZipDownload: vi.fn(() => 'questionnaire-export.zip') }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
const fixture = (): ReviewItem => ({ id: 'item', question: 'Is data encrypted?', owner: null, status: 'needs_review', current_revision: 1,
  provenance: { sheet: 'Security', row: 2, question_cell: 'B2', answer_cell: 'C2', source_identifier: 'SEC-1', writable: true, overwrite_existing: false },
  answer: { text: 'Data is encrypted.', revision: 1, evidence: [{ document_id: 'doc', title: 'Encryption policy', version: 'v1', quote: 'Data is encrypted with AES-256.' }], approval: null } })
function setup(initial = fixture(), extra?: (path: string, init: RequestInit | undefined) => Response | Promise<Response> | undefined) {
  let row = structuredClone(initial)
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
    const path = String(input)
    const override = extra?.(path, init)
    if (override) return override
    if (path === '/api/questionnaires/q') return response({ total: 1, counts: { [row.status]: 1 }, status: 'in_review' })
    if (path.includes('/items?')) return response({ items: [row], total: 1, next_offset: null })
    if (path.endsWith('/item') && (!init?.method || init.method === 'GET')) return response(row)
    if (path.endsWith('/answer')) {
      const body = JSON.parse(init!.body as string)
      row = { ...row, current_revision: row.current_revision + 1, status: 'needs_review', owner: body.owner, answer: { ...row.answer!, revision: row.current_revision + 1, text: body.text, approval: null } }
      return response(row)
    }
    if (path.endsWith('/approve')) {
      const body = JSON.parse(init!.body as string)
      row = { ...row, status: 'approved', answer: { ...row.answer!, approval: { reviewer: body.reviewer, reason: body.reason, identity_verified: 0, created_at: '2026-10-08T01:00:00Z' } } }
      return response(row)
    }
    throw new Error(`Unexpected test route ${path}`)
  })
  const view = render(<ReviewWorkspace client={new ApiClient('test', fetcher)} selection={{ id: 'q', filename: 'security.xlsx' }} />)
  return { ...view, fetcher, setRow: (next: ReviewItem) => { row = next }, getRow: () => row }
}
async function loaded() { await screen.findByRole('heading', { name: 'Is data encrypted?' }) }
const fillReviewer = () => fireEvent.change(screen.getByLabelText('Reviewer label (unverified)'), { target: { value: 'Local reviewer' } })
it('shows source provenance and citations; editing an approved answer requires revision-specific reapproval', async () => {
  const item = fixture(); item.status = 'approved'; item.answer!.approval = { reviewer: 'Previous reviewer', identity_verified: 0, reason: '', created_at: '2026-10-08T01:00:00Z' }
  const { fetcher } = setup(item); await loaded()
  expect(screen.getByText('Data is encrypted with AES-256.')).toBeTruthy()
  expect(screen.getByText(/Encryption policy · Version v1 · Document doc/)).toBeTruthy()
  expect(screen.getByText(/Identifier: SEC-1/)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Approve revision 1' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('Answer text'), { target: { value: 'Reviewed encryption answer.' } })
  fireEvent.change(screen.getByLabelText('Owner label (optional)'), { target: { value: 'Security team' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }))
  await screen.findByText('Revision 2 saved. A new explicit approval is required.')
  expect(screen.queryByText(/approved by Previous/)).toBeNull()
  fillReviewer(); fireEvent.click(screen.getByRole('button', { name: 'Approve revision 2' }))
  await screen.findByText('Revision 2 approved.')
  const patch = fetcher.mock.calls.find(([path]) => String(path).endsWith('/answer'))!
  expect(JSON.parse(patch[1]!.body as string)).toEqual({ text: 'Reviewed encryption answer.', owner: 'Security team', expected_revision: 1 })
  const approvals = fetcher.mock.calls.filter(([path]) => String(path).endsWith('/approve'))
  expect(approvals).toHaveLength(1); expect(JSON.parse(approvals[0][1]!.body as string).expected_revision).toBe(2)
})
it('retains local text on conflict; reload and explicit rebase are required before saving against a new revision', async () => {
  let conflict = true
  const remote = fixture(); remote.current_revision = 2; remote.answer!.revision = 2; remote.answer!.text = 'Someone else edited this.'
  const state = setup(fixture(), path => path.endsWith('/answer') && conflict ? (conflict = false, state.setRow(remote), response({ error: { code: 'revision_conflict', message: 'Reload current revision.' } }, 409)) : undefined)
  await loaded(); fireEvent.change(screen.getByLabelText('Answer text'), { target: { value: 'My unsaved text' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save new revision' })); await screen.findByRole('alert')
  expect((screen.getByLabelText('Answer text') as HTMLTextAreaElement).value).toBe('My unsaved text')
  fireEvent.click(screen.getByRole('button', { name: 'Reload current item' }))
  await screen.findByText('Someone else edited this.')
  expect((screen.getByRole('button', { name: 'Save new revision' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Keep my edits against revision 2' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }))
  await screen.findByText('Revision 3 saved. A new explicit approval is required.')
  const patches = state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/answer'))
  expect(JSON.parse(patches[1][1]!.body as string).expected_revision).toBe(2)
})
it('blocks automatic or duplicate approval after an uncertain response until the current item is reloaded', async () => {
  const row = fixture()
  const state = setup(row, path => {
    if (!path.endsWith('/approve')) return
    const approved = fixture(); approved.status = 'approved'; approved.answer!.approval = { reviewer: 'Local reviewer', reason: '', identity_verified: 0, created_at: '2026-10-08T01:00:00Z' }
    state.setRow(approved)
    return Promise.reject(new Error('Response lost'))
  })
  await loaded(); fillReviewer(); fireEvent.click(screen.getByRole('button', { name: 'Approve revision 1' }))
  expect((await screen.findByRole('alert')).textContent).toContain('server may have saved')
  expect((screen.getByRole('button', { name: 'Approve revision 1' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Reload current item' }))
  await screen.findByText(/Revision 1 approved by Local reviewer/)
  expect(state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/approve'))).toHaveLength(1)
})
it('missing evidence and preserved destinations are clear and cannot imply export eligibility', async () => {
  const row = fixture(); row.provenance.writable = false; row.answer!.evidence = []; row.status = 'needs_evidence'
  setup(row); await loaded(); fillReviewer()
  expect(screen.getByText(/Preserved destination/)).toBeTruthy(); expect(screen.getByText(/Missing evidence: this draft cannot be approved/)).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Approve revision 1' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('Owner label (optional)'), { target: { value: 'Evidence owner' } })
  expect((screen.getByRole('button', { name: 'Save new revision' }) as HTMLButtonElement).disabled).toBe(false)
})
it('drafts bounded batches until remaining reaches zero without approving any answer', async () => {
  const results = [{ drafted: 25, remaining: 30 }, { drafted: 25, remaining: 5 }, { drafted: 5, remaining: 0 }]
  const row = fixture(); row.answer = null; row.current_revision = 0; row.status = 'imported'
  const state = setup(row, path => {
    if (path === '/api/questionnaires/q') return response({ total: 55, counts: { imported: 55 }, status: 'imported' })
    if (path.endsWith('/draft')) return response(results.shift())
  })
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Draft remaining items' }))
  await screen.findByText('Drafting complete. All generated answers still require human review.')
  const batches = state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/draft'))
  expect(batches).toHaveLength(3); expect(batches.every(([, init]) => JSON.parse(init!.body as string).limit === 25)).toBe(true)
  expect(state.fetcher.mock.calls.some(([path]) => String(path).endsWith('/approve'))).toBe(false)
})
it('retains draft failure after refresh and allows resuming remaining items', async () => {
  let failed = false
  const row = fixture(); row.answer = null; row.current_revision = 0; row.status = 'imported'
  setup(row, path => {
    if (path.endsWith('/draft')) { if (!failed) { failed = true; return response({ error: { code: 'temporary_failure', message: 'Try later' } }, 503) }; return response({ drafted: 1, remaining: 0 }) }
  })
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Draft remaining items' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Drafting can be resumed')
  await waitFor(() => expect((screen.getByRole('button', { name: 'Draft remaining items' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: 'Draft remaining items' }))
  await screen.findByText('Drafting complete. All generated answers still require human review.')
})
it('keeps unsaved edits across item pagination and reloads', async () => {
  const row = fixture()
  setup(row, path => {
    if (path.includes('/items?')) return response({ items: path.includes('offset=20') ? [{ ...row, id: 'second', question: 'Second page question' }] : [row], total: 21, next_offset: path.includes('offset=20') ? null : 20 })
  })
  await loaded(); fireEvent.change(screen.getByLabelText('Answer text'), { target: { value: 'Keep this local text' } })
  fireEvent.click(screen.getByRole('button', { name: 'Next items' })); await screen.findByText('Second page question')
  fireEvent.click(screen.getByRole('button', { name: 'Previous items' })); await loaded()
  expect((screen.getByLabelText('Answer text') as HTMLTextAreaElement).value).toBe('Keep this local text')
  fireEvent.click(screen.getByRole('button', { name: 'Reload review page' })); await loaded()
  expect((screen.getByLabelText('Answer text') as HTMLTextAreaElement).value).toBe('Keep this local text')
})

it('stops a stalled draft run and leaves a recoverable error visible', async () => {
  const row = fixture(); row.answer = null; row.current_revision = 0; row.status = 'imported'
  const state = setup(row, path => path.endsWith('/draft') ? response({ drafted: 0, remaining: 1 }) : undefined)
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Draft remaining items' }))
  expect((await screen.findByRole('alert')).textContent).toContain('draft_stalled')
  await waitFor(() => expect((screen.getByRole('button', { name: 'Draft remaining items' }) as HTMLButtonElement).disabled).toBe(false))
  expect(state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/draft'))).toHaveLength(1)
})
it('stopping drafting aborts the request and ignores a late completion', async () => {
  let resolve!: (value: Response) => void
  const row = fixture(); row.answer = null; row.current_revision = 0; row.status = 'imported'
  const state = setup(row, path => path.endsWith('/draft') ? new Promise<Response>(done => { resolve = done }) : undefined)
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Draft remaining items' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Stop drafting' }))
  const call = state.fetcher.mock.calls.find(([path]) => String(path).endsWith('/draft'))!
  expect(call[1]!.signal!.aborted).toBe(true)
  resolve(response({ drafted: 1, remaining: 0 }))
  await screen.findByText(/Drafting stopped/)
  await waitFor(() => expect((screen.getByRole('button', { name: 'Reload review page' }) as HTMLButtonElement).disabled).toBe(false))
  expect(screen.queryByText('Drafting complete. All generated answers still require human review.')).toBeNull()
})

it('exports only after local edits are saved or discarded and displays authoritative receipt counts', async () => {
  const state = setup(fixture(), path => {
    if (path.endsWith('/export')) return new Response('zip bytes', { headers: { 'Content-Type': 'application/zip', 'X-Export-ID': 'receipt-id' } })
    if (path.includes('/exports/')) return response({ export_id: 'receipt-id', questionnaire_id: 'q', created_at: '2026-10-08T01:00:00Z', total: 1, selected_count: 0, unresolved_count: 1, details_available: true, offset: 0, limit: 20, next_offset: null, items: [{ item_id: 'item', question: 'Is data encrypted?', sheet: 'Security', answer_cell: 'C2', owner: null, reason: 'current_revision_not_approved' }] })
  })
  await loaded(); fireEvent.change(screen.getByLabelText('Answer text'), { target: { value: 'Unsaved local answer' } })
  expect((screen.getByRole('button', { name: 'Download export bundle' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Discard local edits' }))
  fireEvent.click(screen.getByRole('button', { name: 'Download export bundle' }))
  await screen.findByText(/0 answers applied.*1 unresolved.*1 total/)
  expect(startZipDownload).toHaveBeenCalledOnce()
  expect(state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/export'))).toHaveLength(1)
})
it('export failures do not start a download or claim bundle success', async () => {
  const state = setup(fixture(), path => path.endsWith('/export') ? response({ error: { code: 'export_failed', message: 'Retry later' } }, 503) : undefined)
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Download export bundle' }))
  expect((await screen.findByRole('alert')).textContent).toContain('No browser download was started')
  expect(startZipDownload).not.toHaveBeenCalled(); expect(screen.queryByText(/Export bundle received/)).toBeNull()
  expect(state.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/export'))).toHaveLength(1)
})
it('unmount aborts export and suppresses a late download result', async () => {
  let resolve!: (value: Response) => void
  const state = setup(fixture(), path => path.endsWith('/export') ? new Promise<Response>(done => { resolve = done }) : undefined)
  await loaded(); fireEvent.click(screen.getByRole('button', { name: 'Download export bundle' }))
  const call = state.fetcher.mock.calls.find(([path]) => String(path).endsWith('/export'))!
  state.unmount(); expect(call[1]!.signal!.aborted).toBe(true)
  resolve(new Response('zip bytes', { headers: { 'Content-Type': 'application/zip', 'X-Export-ID': 'receipt-id' } }))
  await new Promise<void>(done => setTimeout(done, 0))
  expect(startZipDownload).not.toHaveBeenCalled()
})
