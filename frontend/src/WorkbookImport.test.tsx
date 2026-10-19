import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiClient } from './api'
import { WorkbookImport, type WorkbookPreview } from './WorkbookImport'
afterEach(cleanup)
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
const inspection: WorkbookPreview = { sheets: [{ name: 'Security', state: 'visible', rows: 9, candidate_columns: [{ column: 'B', sample: 'Question' }] }, { name: 'Hidden', state: 'hidden', rows: 2, candidate_columns: [] }], mapping: null, total: 0, rows: [], warnings: ['Choose explicitly'] }
const preview: WorkbookPreview = { ...inspection, total: 5, rows: [{ sheet: 'Security', row: 2, question_cell: 'B2', answer_cell: 'C2', source_identifier: 'SEC-1', question: 'Encryption?', writable: false, overwrite_existing: false }], warnings: [{ code: 'existing_answer_preserved', sheet: 'Security', cell: 'C2' }, { code: 'hidden_row_skipped', sheet: 'Security', row: 8 }], preview_limit: 100 }
function setup(fetcher: typeof fetch, maxUploadBytes = 10485760) {
  const onImported = vi.fn()
  const view = render(<WorkbookImport client={new ApiClient('test', (input, init) => input === '/api/questionnaires/limits' ? Promise.resolve(response({ max_upload_bytes: maxUploadBytes })) : fetcher(input, init))} onImported={onImported} />)
  return { ...view, onImported }
}
function upload(name = 'security.xlsx') { fireEvent.change(screen.getByLabelText('Workbook (.xlsx)'), { target: { files: [new File(['synthetic'], name)] } }) }
async function inspect() { upload(); fireEvent.click(screen.getByRole('button', { name: 'Inspect workbook' })); await screen.findByText(/Security — visible/) }
function mapping(sheet = 'Security') {
  fireEvent.click(screen.getByLabelText(`Map ${sheet}`))
  for (const [label, value] of [[`Header row for ${sheet}`, '1'], [`Question column for ${sheet}`, 'B'], [`Answer column for ${sheet}`, 'C']]) fireEvent.change(screen.getByLabelText(label), { target: { value } })
}
it('inspects without mapping and never selects sheet or columns automatically', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(inspection)); setup(fetcher); await inspect()
  const body = fetcher.mock.calls[0][1]!.body as FormData
  expect(body.has('file')).toBe(true); expect(body.has('mapping')).toBe(false)
  expect((screen.getByLabelText('Map Security') as HTMLInputElement).checked).toBe(false)
  expect(screen.queryByRole('button', { name: 'Confirm import' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Select at least one sheet')
  mapping(); expect((screen.getByLabelText('Allow overwriting existing answers for Security') as HTMLInputElement).checked).toBe(false)
})
it('previews exact cells, warnings and truncation before importing; retries retain a key', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(inspection)).mockResolvedValueOnce(response(preview))
    .mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce(response({ id: 'saved', total: 5, status: 'imported' }))
  const { onImported } = setup(fetcher); await inspect(); mapping()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' }))
  await screen.findByText('Security!B2'); expect(screen.getByText('Security!C2')).toBeTruthy()
  expect(screen.getByText(/Existing answer preserved/)).toBeTruthy(); expect(screen.getByText(/Hidden row skipped/)).toBeTruthy()
  expect(screen.getByText(/preview capped at 100/)).toBeTruthy()
  expect(fetcher).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Confirm import' }))
  await screen.findByRole('alert'); fireEvent.click(screen.getByRole('button', { name: 'Confirm import' }))
  await screen.findByText('Workbook imported')
  const first = new Headers(fetcher.mock.calls[2][1]!.headers).get('Idempotency-Key')
  expect(first).toBeTruthy(); expect(new Headers(fetcher.mock.calls[3][1]!.headers).get('Idempotency-Key')).toBe(first)
  expect((fetcher.mock.calls[2][1]!.body as FormData).get('mapping')).toBe((fetcher.mock.calls[3][1]!.body as FormData).get('mapping'))
  expect(onImported).toHaveBeenCalledWith({ id: 'saved', total: 5, status: 'imported' })
  expect(screen.queryByRole('button', { name: 'Confirm import' })).toBeNull()
})
it('requires distinct columns and explicit hidden-sheet intent', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(inspection)); setup(fetcher); await inspect(); mapping('Hidden')
  fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' }))
  expect((await screen.findByRole('alert')).textContent).toContain('hidden_sheet')
  fireEvent.click(screen.getByLabelText('Include hidden rows and sheets for Hidden'))
  fireEvent.change(screen.getByLabelText('Answer column for Hidden'), { target: { value: 'B' } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' }))
  expect((await screen.findByRole('alert')).textContent).toContain('distinct Excel column')
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it('invalidates a preview and changes the retry key when a mapping changes', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(response(inspection)).mockResolvedValueOnce(response(preview))
    .mockResolvedValueOnce(response({ error: { code: 'idempotency_conflict', message: 'Key conflict' } }, 409))
    .mockResolvedValueOnce(response(preview)).mockResolvedValueOnce(response({ id: 'new', total: 5, status: 'imported' }))
  setup(fetcher); await inspect(); mapping(); fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' })); await screen.findByText('Mapped preview')
  fireEvent.click(screen.getByRole('button', { name: 'Confirm import' })); expect((await screen.findByRole('alert')).textContent).toContain('Start another import')
  fireEvent.click(screen.getByLabelText('Allow overwriting existing answers for Security'))
  expect(screen.queryByText('Mapped preview')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Preview mapped questions' })); await screen.findByText('Mapped preview')
  fireEvent.click(screen.getByRole('button', { name: 'Confirm import' })); await screen.findByText('Workbook imported')
  expect(new Headers(fetcher.mock.calls[2][1]!.headers).get('Idempotency-Key')).not.toBe(new Headers(fetcher.mock.calls[4][1]!.headers).get('Idempotency-Key'))
  expect(JSON.parse((fetcher.mock.calls[4][1]!.body as FormData).get('mapping') as string).sheets[0].overwrite_existing).toBe(true)
})
it('shows unsupported formats and backend upload-limit errors', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ error: { code: 'upload_too_large', message: 'Upload exceeds limit.' } }, 413)); setup(fetcher)
  upload('unsupported.xlsm'); expect(screen.getByRole('alert').textContent).toContain('unsupported_format'); expect(fetcher).not.toHaveBeenCalled()
  upload(); fireEvent.click(screen.getByRole('button', { name: 'Inspect workbook' }))
  expect((await screen.findByRole('alert')).textContent).toContain('upload_too_large: Upload exceeds limit.')
})
it('aborts and ignores a late inspection on reset', async () => {
  let resolve!: (value: Response) => void
  const fetcher = vi.fn<typeof fetch>().mockImplementation(() => new Promise<Response>(done => { resolve = done }))
  setup(fetcher); upload(); fireEvent.click(screen.getByRole('button', { name: 'Inspect workbook' }))
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('button', { name: 'Start another import' }))
  resolve(response(inspection)); await waitFor(() => expect((fetcher.mock.calls[0][1]!.signal as AbortSignal).aborted).toBe(true))
  expect(screen.queryByLabelText('Map Security')).toBeNull()
})

it('uses the configured server limit before sending workbook bytes', async () => {
  const fetcher = vi.fn<typeof fetch>(); setup(fetcher, 2); upload()
  fireEvent.click(screen.getByRole('button', { name: 'Inspect workbook' }))
  expect((await screen.findByRole('alert')).textContent).toContain('upload_too_large')
  expect(fetcher).not.toHaveBeenCalled()
})
