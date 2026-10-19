import { WorkflowControls } from './WorkflowControls'
import { ExportPanel, type ExportReceipt } from './ExportPanel'
import { startZipDownload } from './download'
import { useEffect, useRef, useState } from 'react'
import { ApiClient, ApiError, type Session } from './api'

export type ReviewSelection = { id: string; filename: string }
export type Citation = { document_id: string; title: string; version: string; quote: string }
export type Approval = { reviewer: string; identity_verified: number; created_at: string; reason: string }
export type ReviewItem = {
  id: string; question: string; owner: string | null; current_revision: number; status: string
  provenance: { sheet: string; row: number; question_cell: string; answer_cell: string; source_identifier: string | null; writable: boolean; overwrite_existing: boolean }
  answer: { text: string; revision: number; evidence: Citation[]; approval: Approval | null; access_blocked?: boolean; stale_evidence?: boolean; invalidation_reason?: string } | null
}
type ItemPage = { items: ReviewItem[]; total: number; next_offset: number | null }
type Summary = { total: number; counts: Record<string, number>; status: string }
type LocalEdit = { text: string; owner: string; baseRevision: number }
type Issue = { message: string; reload: boolean }
const PAGE_SIZE = 20
const BATCH_SIZE = 25
const errorMessage = (cause: unknown) => cause instanceof ApiError ? `${cause.code}: ${cause.message}` : cause instanceof Error ? cause.message : 'Request failed. Try again.'
const statusLabel: Record<string, string> = { imported: 'Not drafted', needs_review: 'Needs review', needs_evidence: 'Needs evidence', approved: 'Approved' }

export function ReviewWorkspace({ client, selection, session }: { client: ApiClient; selection: ReviewSelection; session?: Session }) {
  const verified = session?.authentication === 'oidc'
  const canAuthor = !verified || !!session.roles?.some(role => ['author','admin'].includes(role))
  const canReview = !verified || !!session.roles?.some(role => ['reviewer','admin'].includes(role))
  const [workflowActivity, setWorkflowActivity] = useState<Record<string, boolean>>({})
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [items, setItems] = useState<ItemPage | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [exportError, setExportError] = useState('')
  const [receipt, setReceipt] = useState<ExportReceipt | null>(null)
  const [draftError, setDraftError] = useState('')
  const [progress, setProgress] = useState('')
  const [edits, setEdits] = useState<Record<string, LocalEdit>>({})
  const [issues, setIssues] = useState<Record<string, Issue>>({})
  const [notices, setNotices] = useState<Record<string, string>>({})
  const [reviewer, setReviewer] = useState('')
  const [reason, setReason] = useState('')
  const action = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; action.current?.abort() } }, [])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setItems(null)
    void Promise.all([
      client.json<Summary>(`/questionnaires/${selection.id}`, { signal: controller.signal }),
      client.json<ItemPage>(`/questionnaires/${selection.id}/items?offset=${offset}&limit=${PAGE_SIZE}`, { signal: controller.signal }),
    ]).then(([loadedSummary, loadedItems]) => {
      if (!controller.signal.aborted) { setSummary(loadedSummary); setItems(loadedItems); setEdits(current => Object.fromEntries(Object.entries(current).filter(([id]) => !loadedItems.items.find(row => row.id === id)?.answer?.access_blocked))) }
    }).catch(cause => { if (!controller.signal.aborted) setError(errorMessage(cause)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, selection.id, offset, refresh])

  function putIssue(id: string, issue: Issue | null) {
    setIssues(current => { const next = { ...current }; if (issue) next[id] = issue; else delete next[id]; return next })
  }
  function removeEdit(id: string) { setEdits(current => { const next = { ...current }; delete next[id]; return next }) }
  function change(item: ReviewItem, patch: Partial<LocalEdit>) {
    setEdits(current => ({ ...current, [item.id]: { ...(current[item.id] ?? { text: item.answer?.text || '', owner: item.owner || '', baseRevision: item.current_revision }), ...patch } }))
    setNotices(current => ({ ...current, [item.id]: '' }))
  }
  function commit(item: ReviewItem) {
    if (item.answer?.access_blocked) removeEdit(item.id)
    setItems(current => current && ({ ...current, items: current.items.map(row => row.id === item.id ? item : row) }))
  }
  async function summaryAfterChange(signal: AbortSignal) {
    try {
      const result = await client.json<Summary>(`/questionnaires/${selection.id}`, { signal })
      if (!signal.aborted) setSummary(result)
    } catch (cause) { if (!signal.aborted) setError(`Change saved, but counts could not refresh. Reload the page. ${errorMessage(cause)}`) }
  }
  async function run(label: string, operation: (signal: AbortSignal) => Promise<void>, itemId?: string, mutation = false) {
    if (action.current || loading) return
    const controller = new AbortController(); action.current = controller
    setBusy(label); setError('')
    if (itemId) { if (label !== 'Reloading current item') putIssue(itemId, null); setNotices(current => ({ ...current, [itemId]: '' })) }
    let timedOut = false
    const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, label === 'Drafting remaining items' ? 120000 : 30000)
    try { await operation(controller.signal) }
    catch (cause) {
      if (!controller.signal.aborted || timedOut) {
        const uncertain = mutation && (timedOut || !(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500)
        const message = `${timedOut ? 'Request timed out.' : errorMessage(cause)}${uncertain ? ' The server may have saved the action. Reload the current item before trying again.' : ''}`
        if (itemId) putIssue(itemId, { message, reload: label === 'Reloading current item' || uncertain || (cause instanceof ApiError && ['revision_conflict', 'already_approved', 'stale_evidence'].includes(cause.code)) })
        else if (label === 'Preparing export bundle') setExportError(`${message} No browser download was started. Retry explicitly to generate a new export snapshot.`)
        else setDraftError(`${message} Drafting can be resumed; previously drafted items are skipped.`)
      }
    } finally {
      window.clearTimeout(timer)
      if (action.current === controller) {
        action.current = null
        if (mounted.current) {
          setBusy('')
          if (label === 'Drafting remaining items') setRefresh(value => value + 1)
        }
      }
    }
  }
  async function draft() {
    setDraftError('')
    await run('Drafting remaining items', async signal => {
      let previousRemaining = Infinity
      const maximumBatches = 201
      setProgress('Starting bounded draft batches…')
      for (let batch = 1; batch <= maximumBatches; batch++) {
        const result = await client.json<{ drafted: number; remaining: number }>(`/questionnaires/${selection.id}/draft`, { method: 'POST', body: { limit: BATCH_SIZE }, signal })
        if (signal.aborted) return
        if (!Number.isInteger(result.remaining) || result.remaining < 0 || !Number.isInteger(result.drafted) || result.drafted < 0) throw new ApiError('invalid_response', 'Unexpected drafting progress.', 0)
        setProgress(`Batch ${batch}: ${result.drafted} drafted; ${result.remaining} remaining.`)
        if (result.remaining === 0) { setProgress('Drafting complete. All generated answers still require human review.'); return }
        if (result.remaining >= previousRemaining || result.drafted === 0) throw new ApiError('draft_stalled', 'Drafting made no progress. Reload or resume the remaining items.', 0)
        previousRemaining = result.remaining
      }
      throw new ApiError('draft_batch_limit', 'This run reached its batch limit. Resume to process remaining items.', 0)
    })
  }
  function stopDrafting() {
    action.current?.abort()
    setProgress('Drafting stopped. A batch already received by the server may finish. Reload or resume remaining items.')
  }
  async function reloadItem(item: ReviewItem) {
    await run('Reloading current item', async signal => {
      const result = await client.json<ReviewItem>(`/questionnaire-items/${item.id}`, { signal })
      if (signal.aborted) return
      commit(result); putIssue(item.id, null)
      setNotices(current => ({ ...current, [item.id]: 'Current revision reloaded. Your unsaved text has been kept for comparison.' }))
      await summaryAfterChange(signal)
    }, item.id)
  }
  async function save(item: ReviewItem) {
    const local = edits[item.id]
    if (!local || local.baseRevision !== item.current_revision || issues[item.id]?.reload) return
    if (!local.text.trim() || local.text.length > 10000 || local.owner.length > 200) { putIssue(item.id, { message: 'Enter answer text (1–10,000 characters) and an owner label of at most 200 characters.', reload: false }); return }
    await run('Saving answer revision', async signal => {
      const result = await client.json<ReviewItem>(`/questionnaire-items/${item.id}/answer`, { method: 'PATCH', body: { text: local.text, expected_revision: local.baseRevision, owner: local.owner }, signal })
      if (signal.aborted) return
      commit(result); removeEdit(item.id)
      setNotices(current => ({ ...current, [item.id]: `Revision ${result.current_revision} saved. A new explicit approval is required.` }))
      await summaryAfterChange(signal)
    }, item.id, true)
  }
  async function approve(item: ReviewItem) {
    if (!item.answer || !item.answer.evidence.length || item.answer.approval || edits[item.id] || issues[item.id]?.reload || (!verified && !reviewer.trim())) return
    await run('Approving current revision', async signal => {
      const result = await client.json<ReviewItem>(`/questionnaire-items/${item.id}/approve`, { method: 'POST', body: { expected_revision: item.current_revision, ...(verified ? {} : { reviewer: reviewer.trim() }), reason }, signal })
      if (signal.aborted) return
      commit(result)
      setNotices(current => ({ ...current, [item.id]: `Revision ${result.current_revision} approved.` }))
      await summaryAfterChange(signal)
    }, item.id, true)
  }
  async function downloadExport() {
    if (Object.keys(edits).length || Object.values(issues).some(issue => issue.reload)) return
    setExportError('')
    await run('Preparing export bundle', async signal => {
      const output = await client.download(`/questionnaires/${selection.id}/export`, 'POST', signal)
      if (signal.aborted) return
      if (!output.blob.size || !['application/zip', 'application/x-zip-compressed'].includes(output.blob.type.split(';')[0])) throw new ApiError('invalid_response', 'The API did not return a ZIP export bundle.', 0)
      const filename = startZipDownload(output.blob, output.filename)
      setReceipt({ filename, exportId: output.exportId })
      await summaryAfterChange(signal)
    })
  }
  const blocked = loading || !!busy || Object.values(workflowActivity).some(Boolean)
  return <section className="review-workspace" aria-label="Questionnaire review">
    <section className="task-card review-toolbar"><h2>Review {selection.filename}</h2><p>Questionnaire: {selection.id}</p>
      <p>Extractive drafts quote legacy evidence; they are not factually verified. Check each claim and source before approving. {verified ? 'Reviewer identity comes from verified authentication; owner names are local labels.' : 'Reviewer and owner names are unverified local labels.'}</p>
      {summary && <p>{summary.total} items · Questionnaire status: {summary.status} · {Object.entries(summary.counts).map(([status, count]) => `${statusLabel[status] || status}: ${count}`).join(' · ')}</p>}
      <div className="review-actions"><button className="primary-button" disabled={blocked || !canAuthor || !summary || !summary.counts.imported} onClick={() => void draft()}>Draft remaining items</button>
        {busy === 'Drafting remaining items' && <button className="secondary-button" onClick={stopDrafting}>Stop drafting</button>}
        <button className="secondary-button" disabled={blocked} onClick={() => setRefresh(value => value + 1)}>Reload review page</button></div>
      {progress && <p role="status">{progress}</p>}{busy && <p role="status">{busy}…</p>}{loading && <p role="status">Loading review items…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}{draftError && <p className="error-message" role="alert">{draftError}</p>}
      {verified && <p>Verified reviewer: {session?.subject}. Current roles: {session?.roles?.join(', ')}. Approval is attributed to your verified identity. Approval/export require reviewer or admin; drafting/editing require author or admin.</p>}<div className="mapping-grid"><div><label htmlFor="reviewer-label">{verified ? 'Reviewer identity (from authentication)' : 'Reviewer label (unverified)'}</label><input id="reviewer-label" maxLength={200} disabled={blocked || verified} value={verified ? session?.subject : reviewer} onChange={event => setReviewer(event.target.value)} /></div>
        <div><label htmlFor="review-reason">Approval reason (optional)</label><input id="review-reason" maxLength={1000} disabled={blocked} value={reason} onChange={event => setReason(event.target.value)} /></div></div>
      <p className="field-help">Unsaved edits are kept in memory across item pages and workspace tabs. Changing questionnaires, refreshing the browser or disconnecting clears them.</p>
    </section>
    <ExportPanel client={client} questionnaireId={selection.id} disabled={blocked || !summary || !canReview} unsaved={!!Object.keys(edits).length} recoveryRequired={Object.values(issues).some(issue => issue.reload)} receipt={receipt} error={exportError} onDownload={() => void downloadExport()} />
    {items && <><div className="pagination"><button disabled={blocked || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous items</button><span>Item page {offset / PAGE_SIZE + 1} · {items.total} total</span><button disabled={blocked || items.next_offset === null} onClick={() => setOffset(items.next_offset!)}>Next items</button></div>
      {!items.items.length && <p>No items on this page.</p>}
      {items.items.map(item => {
        const local = edits[item.id]
        const conflict = !!local && local.baseRevision !== item.current_revision
        const issue = issues[item.id]
        const hasEvidence = !!item.answer?.evidence.length && !item.answer?.stale_evidence && !item.answer?.access_blocked && !item.answer?.invalidation_reason
        const approved = !!item.answer?.approval
        return <article className="task-card review-item" key={item.id} aria-labelledby={`question-${item.id}`}>
          <div className="review-item-heading"><h3 id={`question-${item.id}`}>{item.question}</h3><span className={`review-status ${approved ? 'approved' : ''}`}>{statusLabel[item.status] || item.status} · Revision {item.current_revision}</span></div>
          <p className="source-location">{item.provenance.sheet} · Row {item.provenance.row} · Identifier: {item.provenance.source_identifier || 'None'} · {item.provenance.question_cell} → {item.provenance.answer_cell}</p>
          {!item.provenance.writable ? <p className="destination-note">Preserved destination: the original answer in {item.provenance.sheet}!{item.provenance.answer_cell} remains unchanged on export, even if this draft is approved.</p> : item.provenance.overwrite_existing ? <p className="destination-note">Overwrite was explicitly allowed at import. Export still requires approval of the current revision.</p> : null}
          {verified && item.answer && (item.answer.access_blocked || item.answer.stale_evidence || item.answer.invalidation_reason) && <p className="error-message">Evidence access or validity changed. Approval is invalidated; redraft from current approved, authorized sources.</p>}
          {verified && item.answer && canAuthor && <button className="secondary-button" disabled={blocked || !!local} onClick={() => void run('Redrafting item', async signal => { const result = await client.json<ReviewItem>(`/questionnaire-items/${item.id}/redraft`, { method: 'POST', body: { expected_revision: item.current_revision }, signal }); if (!signal.aborted) { commit(result); await summaryAfterChange(signal) } }, item.id, true)}>Redraft from current evidence</button>}
          {!item.answer ? <p>No draft yet. Use Draft remaining items.</p> : <>
            <section aria-label="Evidence citations"><h4>Evidence citations</h4>{hasEvidence ? item.answer.evidence.map((citation, index) => <figure key={`${citation.document_id}-${index}`}><blockquote>{citation.quote}</blockquote><figcaption>{citation.title} · Version {citation.version} · Document {citation.document_id}</figcaption></figure>) : <p className="destination-note">Missing evidence: this draft cannot be approved. Assign an owner to resolve it; editing text does not supply evidence. Adding evidence does not automatically redraft an existing revision.</p>}</section>
            <section aria-label="Saved answer"><h4>Saved answer · Revision {item.current_revision}</h4><p className="answer-text">{item.answer.text}</p><p>Saved owner: {item.owner || 'Unassigned'}</p></section>
            {approved && <p className="approval-note">Revision {item.current_revision} approved by {item.answer.approval!.reviewer} ({verified ? 'verified identity' : 'unverified local label'}) at {new Date(item.answer.approval!.created_at).toLocaleString()}.{item.answer.approval!.reason && ` Reason: ${item.answer.approval!.reason}`}</p>}
            {local && <p className="destination-note">Unsaved edits · Based on revision {local.baseRevision}. Saving creates a new revision and requires reapproval.</p>}
            <label htmlFor={`answer-${item.id}`}>Answer text</label><textarea id={`answer-${item.id}`} rows={5} maxLength={10000} disabled={blocked || !canAuthor || !!item.answer.access_blocked} value={local?.text ?? item.answer.text} onChange={event => change(item, { text: event.target.value })} />
            <label htmlFor={`owner-${item.id}`}>Owner label (optional)</label><input id={`owner-${item.id}`} maxLength={200} disabled={blocked || !canAuthor || !!item.answer.access_blocked} value={local?.owner ?? item.owner ?? ''} onChange={event => change(item, { owner: event.target.value })} />
            {conflict && <p role="alert" className="error-message">Your edits are based on revision {local.baseRevision}; the saved answer is now revision {item.current_revision}. Compare both before choosing how to proceed.</p>}
            {conflict && <button className="secondary-button" disabled={blocked} onClick={() => { change(item, { baseRevision: item.current_revision }); putIssue(item.id, null) }}>Keep my edits against revision {item.current_revision}</button>}
            <div className="review-actions"><button className="primary-button" disabled={blocked || !canAuthor || !!item.answer.access_blocked || !local || conflict || issue?.reload || !local.text.trim()} onClick={() => void save(item)}>Save new revision</button>
              {local && <button className="secondary-button" disabled={blocked} onClick={() => removeEdit(item.id)}>Discard local edits</button>}
              <button className="secondary-button" disabled={blocked} onClick={() => void reloadItem(item)}>Reload current item</button>
              <button className="primary-button" disabled={blocked || !canReview || approved || !!local || !!issue?.reload || !hasEvidence || (!verified && !reviewer.trim())} onClick={() => void approve(item)}>Approve revision {item.current_revision}</button></div>
            {!verified && !reviewer.trim() && !approved && hasEvidence && <p className="field-help">Enter a reviewer label above before approving.</p>}
          </>}
          {verified && session && <WorkflowControls client={client} itemId={item.id} revision={item.current_revision} session={session} disabled={blocked || !!local || !!issue?.reload} onActive={active => setWorkflowActivity(current => ({ ...current, [item.id]: active }))} onChanged={async signal => { const loaded = await client.json<ReviewItem>(`/questionnaire-items/${item.id}`, { signal }); if (!signal.aborted) { commit(loaded); await summaryAfterChange(signal) } }} />}
          {issue && <p role="alert" className="error-message">{issue.message}{issue.reload && ' Use Reload current item to fetch the saved revision.'}</p>}
          {notices[item.id] && <p role="status">{notices[item.id]}</p>}
        </article>
      })}
    </>}
  </section>
}
