import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiClient, ApiError } from './api'

export type Sheet = { name: string; state: string; rows: number; candidate_columns: { column: string; sample: string }[] }
export type SheetMapping = { sheet: string; header_row: number; question_column: string; answer_column: string; identifier_column: string | null; include_hidden: boolean; overwrite_existing: boolean }
export type WorkbookMapping = { sheets: SheetMapping[] }
type DraftMapping = { selected: boolean; header: string; question: string; answer: string; identifier: string; hidden: boolean; overwrite: boolean }
export type PreviewRow = { sheet: string; row: number; question_cell: string; answer_cell: string; source_identifier: string | null; question: string; writable: boolean; overwrite_existing: boolean }
export type WorkbookPreview = { sheets: Sheet[]; mapping: WorkbookMapping | null; rows: PreviewRow[]; total: number; warnings: (string | { code: string; sheet: string; row?: number; cell?: string })[]; preview_limit?: number }
type ConfirmedPreview = { result: WorkbookPreview; mapping: WorkbookMapping }
export type ImportedWorkbook = { id: string; total: number; status: string }
const blank = (): DraftMapping => ({ selected: false, header: '', question: '', answer: '', identifier: '', hidden: false, overwrite: false })
const warningText: Record<string, string> = {
  hidden_row_skipped: 'Hidden row skipped',
  existing_answer_preserved: 'Existing answer preserved; this destination will not be changed',
  existing_answer_overwrite: 'Existing answer may be overwritten after a current answer is approved',
}
const columnNumber = (value: string) => [...value].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0)

export function WorkbookImport({ client, onImported }: { client: ApiClient; onImported: (result: ImportedWorkbook) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [inspection, setInspection] = useState<WorkbookPreview | null>(null)
  const [drafts, setDrafts] = useState<DraftMapping[]>([])
  const [preview, setPreview] = useState<ConfirmedPreview | null>(null)
  const [saved, setSaved] = useState<ImportedWorkbook | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const idempotencyKey = useRef<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  useEffect(() => () => request.current?.abort(), [])

  function reset() {
    request.current?.abort(); request.current = null
    idempotencyKey.current = null
    setFile(null); setInspection(null); setDrafts([]); setPreview(null); setSaved(null); setError(''); setBusy('')
    if (fileInput.current) fileInput.current.value = ''
  }
  function changeFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] || null
    reset()
    if (selected && !selected.name.toLowerCase().endsWith('.xlsx')) {
      setError('unsupported_format: Upload an unencrypted .xlsx workbook. .xls and .xlsm are unsupported.')
      return
    }
    setFile(selected)
  }
  function edit(index: number, patch: Partial<DraftMapping>) {
    setDrafts(current => current.map((draft, position) => position === index ? { ...draft, ...patch } : draft))
    setPreview(null); setError(''); idempotencyKey.current = null
  }
  function form(mapping?: WorkbookMapping) {
    const body = new FormData()
    body.append('file', file!)
    if (mapping) body.append('mapping', JSON.stringify(mapping))
    return body
  }
  function fail(cause: unknown) {
    if (cause instanceof ApiError) {
      setError(`${cause.code}: ${cause.message}${cause.code === 'idempotency_conflict' ? ' This import key was already used. Start another import to intentionally create a new request.' : ''}`)
    } else setError(cause instanceof Error ? cause.message : 'Request failed. Try again.')
  }
  async function run(label: string, operation: (signal: AbortSignal) => Promise<void>) {
    if (request.current) return
    const controller = new AbortController(); request.current = controller
    setBusy(label); setError('')
    try { await operation(controller.signal) }
    catch (cause) { if (!controller.signal.aborted) fail(cause) }
    finally { if (request.current === controller) { request.current = null; setBusy('') } }
  }
  async function inspectFile() {
    if (!file) return
    await run('Inspecting workbook…', async signal => {
      const limits = await client.json<{ max_upload_bytes: number }>('/questionnaires/limits', { signal })
      if (signal.aborted) return
      if (!Number.isSafeInteger(limits.max_upload_bytes) || limits.max_upload_bytes < 1) throw new ApiError('invalid_response', 'The API returned an invalid workbook upload limit.', 0)
      if (file.size > limits.max_upload_bytes) throw new ApiError('upload_too_large', `Workbook exceeds the configured upload limit (${limits.max_upload_bytes.toLocaleString()} bytes).`, 413)
      const result = await client.upload<WorkbookPreview>('/questionnaires/preview', form(), undefined, signal)
      if (signal.aborted) return
      setInspection(result); setDrafts(result.sheets.map(blank)); setPreview(null)
    })
  }
  async function previewMapping(event: FormEvent) {
    event.preventDefault()
    if (!inspection || !file) return
    const selected = inspection.sheets.map((sheet, index) => ({ sheet, draft: drafts[index] })).filter(({ draft }) => draft.selected)
    if (!selected.length) { setError('Select at least one sheet and enter its mapping explicitly.'); return }
    const sheets: SheetMapping[] = []
    for (const { sheet, draft } of selected) {
      const columns = [draft.question, draft.answer, ...(draft.identifier ? [draft.identifier] : [])]
      if (!/^\d+$/.test(draft.header) || Number(draft.header) < 1 || Number(draft.header) > Math.min(sheet.rows, 20000) || columns.some(value => !/^[A-Z]{1,3}$/.test(value) || columnNumber(value) > 16384) || new Set(columns).size !== columns.length) {
        setError(`invalid_mapping: ${sheet.name} requires an existing header row and distinct Excel column letters from A to XFD.`); return
      }
      if (sheet.state !== 'visible' && !draft.hidden) { setError(`hidden_sheet: Explicitly include hidden rows and sheets to map ${sheet.name}.`); return }
      sheets.push({ sheet: sheet.name, header_row: Number(draft.header), question_column: draft.question, answer_column: draft.answer, identifier_column: draft.identifier || null, include_hidden: draft.hidden, overwrite_existing: draft.overwrite })
    }
    const mapping = { sheets }
    setPreview(null)
    await run('Building mapped preview…', async signal => {
      const result = await client.upload<WorkbookPreview>('/questionnaires/preview', form(mapping), undefined, signal)
      if (!signal.aborted) setPreview({ result, mapping })
    })
  }
  async function confirm() {
    if (!preview || !file || saved) return
    // Retain this key after network/server failures; only payload edits or an intentional reset replace it.
    idempotencyKey.current ??= crypto.randomUUID()
    await run('Importing confirmed workbook…', async signal => {
      const result = await client.upload<ImportedWorkbook>('/questionnaires', form(preview.mapping), idempotencyKey.current!, signal)
      if (signal.aborted) return
      setSaved(result); setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      onImported(result)
    })
  }

  return <section className="task-card import-card" aria-labelledby="import-heading" aria-busy={!!busy}>
    <div className="import-heading"><h3 id="import-heading">Import a questionnaire workbook</h3><button className="secondary-button" type="button" onClick={reset}>Start another import</button></div>
    <p>Choose an ordinary, unencrypted .xlsx workbook. The default server upload limit is 10 MiB; the backend enforces its configured limits. Uploaded files stay in memory while you map them and are cleared after import or when you leave this page.</p>
    {!saved && <><label htmlFor="workbook-file">Workbook (.xlsx)</label><input ref={fileInput} id="workbook-file" type="file" accept=".xlsx" disabled={!!busy} onChange={changeFile} />
      {file && <p>Selected: {file.name} ({Math.ceil(file.size / 1024)} KiB)</p>}
      <button className="primary-button" type="button" disabled={!file || !!busy || !!inspection} onClick={() => void inspectFile()}>Inspect workbook</button></>}
    {busy && <p role="status">{busy}</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {inspection && !saved && <form onSubmit={previewMapping}>
      <p>Row-1 samples below are inspection aids. Choose each sheet, header row and column yourself; no mapping is selected automatically.</p>
      <fieldset className="mapping-controls" disabled={!!busy}>
        {inspection.sheets.map((sheet, index) => {
          const draft = drafts[index]
          const prefix = `mapping-${index}`
          return <fieldset className="sheet-mapping" key={sheet.name}>
            <legend>{sheet.name} — {sheet.state} · {sheet.rows} rows</legend>
            <label className="check-field"><input type="checkbox" checked={draft.selected} onChange={event => edit(index, { selected: event.target.checked })} />Map {sheet.name}</label>
            <details><summary>Candidate columns in {sheet.name} (row-1 samples)</summary><ul>{sheet.candidate_columns.map(column => <li key={column.column}><strong>{column.column}</strong>: {column.sample || '(empty)'}</li>)}</ul></details>
            {draft.selected && <div className="mapping-grid">
              <div><label htmlFor={`${prefix}-header`}>Header row for {sheet.name}</label><input id={`${prefix}-header`} type="number" required min={1} max={Math.min(sheet.rows, 20000)} value={draft.header} onChange={event => edit(index, { header: event.target.value })} /></div>
              <div><label htmlFor={`${prefix}-question`}>Question column for {sheet.name}</label><input id={`${prefix}-question`} required maxLength={3} placeholder="Excel letters, e.g. B" value={draft.question} onChange={event => edit(index, { question: event.target.value.toUpperCase().trim() })} /></div>
              <div><label htmlFor={`${prefix}-answer`}>Answer column for {sheet.name}</label><input id={`${prefix}-answer`} required maxLength={3} placeholder="Excel letters, e.g. C" value={draft.answer} onChange={event => edit(index, { answer: event.target.value.toUpperCase().trim() })} /></div>
              <div><label htmlFor={`${prefix}-identifier`}>Identifier column for {sheet.name} (optional)</label><input id={`${prefix}-identifier`} maxLength={3} placeholder="Leave empty if unused" value={draft.identifier} onChange={event => edit(index, { identifier: event.target.value.toUpperCase().trim() })} /></div>
              <label className="check-field"><input type="checkbox" checked={draft.hidden} onChange={event => edit(index, { hidden: event.target.checked })} />Include hidden rows and sheets for {sheet.name}</label>
              <p className="field-help">Hidden rows are skipped by default. A hidden sheet requires this explicit selection to import its questions.</p>
              <label className="check-field"><input type="checkbox" checked={draft.overwrite} onChange={event => edit(index, { overwrite: event.target.checked })} />Allow overwriting existing answers for {sheet.name}</label>
              <p className="field-help">Existing answers are preserved by default. Selecting this permits replacement of literal answers only after review and approval; formula destinations are always rejected.</p>
            </div>}
          </fieldset>
        })}
        <button className="primary-button" type="submit">Preview mapped questions</button>
      </fieldset>
    </form>}
    {preview && !saved && <section aria-labelledby="preview-heading"><h3 id="preview-heading">Mapped preview</h3><p>{preview.result.total} questions total. Showing {preview.result.rows.length} rows{preview.result.total > preview.result.rows.length ? ` (preview capped at ${preview.result.preview_limit || 100}; every mapped question will be imported)` : ''}.</p>
      <div className="preview-warnings"><h4>Warnings</h4>{preview.result.warnings.length ? <ul>{preview.result.warnings.slice(0, 100).map((warning, index) => <li key={index}>{typeof warning === 'string' ? warning : `${warningText[warning.code] || warning.code}: ${warning.sheet}${warning.cell ? `!${warning.cell}` : ` row ${warning.row}`}`}</li>)}</ul> : <p>No mapping warnings.</p>}{preview.result.warnings.length > 100 && <p>Showing the first 100 of {preview.result.warnings.length} warnings.</p>}</div>
      <div className="table-scroll"><table><caption>Exact source and destination cells</caption><thead><tr><th>Question</th><th>Identifier</th><th>Source cell</th><th>Destination cell</th><th>Destination behavior</th></tr></thead><tbody>{preview.result.rows.map(row => <tr key={`${row.sheet}:${row.answer_cell}`}><td>{row.question}</td><td>{row.source_identifier || '—'}</td><td>{row.sheet}!{row.question_cell}</td><td>{row.sheet}!{row.answer_cell}</td><td>{!row.writable ? 'Preserve existing answer' : row.overwrite_existing ? 'Overwrite allowed after approval' : 'Write only after approval'}</td></tr>)}</tbody></table></div>
      <p>Confirm this file and mapping to save {preview.result.total} questions. This creates an unapproved questionnaire; open it below and select Review answers. If a request fails, Confirm import retries the same payload with the same request key.</p>
      <button className="primary-button" type="button" disabled={!!busy} onClick={() => void confirm()}>Confirm import</button>
    </section>}
    {saved && <div role="status"><h3>Workbook imported</h3><p>{saved.total} questions saved · {saved.status}</p><p>Questionnaire ID: {saved.id}</p><p>The dashboard has been refreshed. Open the saved questionnaire below.</p></div>}
  </section>
}
