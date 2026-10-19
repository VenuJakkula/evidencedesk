import { useEffect, useState } from 'react'
import { ApiClient, ApiError } from './api'

export type ExportReceipt = { exportId?: string; filename: string }
export type ExportSummary = {
  export_id: string; questionnaire_id: string; created_at: string; total: number; selected_count: number; unresolved_count: number
  details_available: boolean; offset: number; limit: number; next_offset: number | null
  items: { item_id: string; question: string | null; sheet: string | null; answer_cell: string | null; owner: string | null; reason: string }[]
}
const reasons: Record<string, string> = {
  existing_answer_preserved: 'Existing answer preserved',
  current_revision_not_approved: 'Current revision not approved',
  stale_evidence: 'Evidence missing, changed or expired',
  details_unavailable: 'Historical receipt: read the unresolved CSV for details',
}

export function ExportPanel({ client, questionnaireId, disabled, unsaved, recoveryRequired, receipt, error, onDownload }: {
  client: ApiClient; questionnaireId: string; disabled: boolean; unsaved: boolean; recoveryRequired: boolean
  receipt: ExportReceipt | null; error: string; onDownload: () => void
}) {
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [summary, setSummary] = useState<ExportSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [receiptError, setReceiptError] = useState('')
  useEffect(() => { setOffset(0) }, [receipt?.exportId])
  useEffect(() => {
    if (!receipt?.exportId) { setSummary(null); return }
    const controller = new AbortController()
    setLoading(true); setSummary(null); setReceiptError('')
    client.json<ExportSummary>(`/questionnaires/${questionnaireId}/exports/${receipt.exportId}?offset=${offset}&limit=20`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setSummary(result) })
      .catch(cause => { if (!controller.signal.aborted) setReceiptError(cause instanceof ApiError ? `${cause.code}: ${cause.message}` : 'Could not load export receipt.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, questionnaireId, receipt?.exportId, offset, refresh])
  return <section className="task-card export-panel" aria-labelledby="export-heading">
    <h2 id="export-heading">Export and download</h2>
    <p>The backend applies only approved current revisions whose evidence is still valid. Preserved answers and formulas remain unchanged. Unsaved text is not exported; saving an edited answer requires reapproval before it is included.</p>
    <ul className="bundle-files"><li><strong>completed.xlsx</strong> — your workbook with eligible answers filled into mapped cells.</li><li><strong>unresolved-items.csv</strong> — items excluded from export, with owners and reasons.</li><li><strong>manifest.json</strong> — selected revision IDs, exact cells, unresolved items and workbook checksums.</li></ul>
    <button className="primary-button" disabled={disabled || unsaved || recoveryRequired} onClick={onDownload}>Download export bundle</button>
    {unsaved && <p className="destination-note">Save or discard all unsaved edits before exporting, including edits on other item pages.</p>}
    {recoveryRequired && <p className="destination-note">Reload items with unresolved save or approval errors before exporting.</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {receipt && <div className="export-receipt"><p role="status">Export bundle received from the API. Browser download started: {receipt.filename}. Check your browser downloads for the saved file.</p>
      <p>This receipt describes the last received bundle. Later edits and approvals do not change that file; download again for a new snapshot.</p>
      {!receipt.exportId && <p>Receipt metadata is unavailable. Read the ZIP manifest and unresolved CSV for the actual export result.</p>}
      {loading && <p role="status">Loading export receipt…</p>}
      {receiptError && <><p className="error-message" role="alert">Bundle received, but its receipt could not load. {receiptError} The downloaded CSV and manifest remain authoritative.</p><button className="secondary-button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>Reload export receipt</button></>}
      {summary && <section aria-label="Export receipt"><h3>Last export result</h3><p>{summary.selected_count} answers applied · {summary.unresolved_count} unresolved · {summary.total} total</p><p>Export {summary.export_id} · {new Date(summary.created_at).toLocaleString()}</p>
        <p>Unresolved items at export time stay below for review. Preserved destinations remain unresolved even if approved. Use the current review cards to resolve outstanding work.</p>
        {!summary.details_available && <p>This historical export predates detailed receipts. Its CSV contains the original unresolved reasons.</p>}
        {summary.items.length ? <div className="table-scroll"><table><caption>Unresolved items in this bundle</caption><thead><tr><th>Question</th><th>Destination</th><th>Owner at export</th><th>Reason</th></tr></thead><tbody>{summary.items.map(item => <tr key={item.item_id}><td>{item.question || item.item_id}</td><td>{item.sheet && item.answer_cell ? `${item.sheet}!${item.answer_cell}` : 'See CSV'}</td><td>{item.owner || 'Unassigned'}</td><td>{reasons[item.reason] || item.reason}</td></tr>)}</tbody></table></div> : <p>{summary.unresolved_count ? 'No unresolved items on this page.' : 'No unresolved items in this bundle.'}</p>}
        <div className="pagination"><button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous unresolved items</button><span>Receipt page {offset / 20 + 1}</span><button disabled={loading || summary.next_offset === null} onClick={() => setOffset(summary.next_offset!)}>Next unresolved items</button></div>
      </section>}
    </div>}
  </section>
}
