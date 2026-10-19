import { WorkbookImport } from './WorkbookImport'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiClient } from './api'

type Summary = { id: string; filename: string; status: string; created_at: string; total: number }
type Listing = { items: Summary[]; total: number; next_offset: number | null }
type Saved = { id: string; status: string; total: number; created_at: string }
const message = (cause: unknown) => cause instanceof Error ? cause.message : 'Request failed. Try again.'

export function Dashboard({ client, onReview, canImport = true }: { client: ApiClient; canImport?: boolean; onReview?: (selection: { id: string; filename: string }) => void }) {
  const [offset, setOffset] = useState(0)
  const [listing, setListing] = useState<Listing | null>(null)
  const [saved, setSaved] = useState<Saved | null>(null)
  const [filename, setFilename] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setListing(null); setSaved(null)
    client.json<Listing>(`/questionnaires?offset=${offset}&limit=20`, { signal: controller.signal })
      .then(setListing).catch(cause => { if (!controller.signal.aborted) setError(message(cause)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, offset, refresh])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  useEffect(() => {
    if (!selectedId) return
    const controller = new AbortController()
    setSaved(null); setError(''); setLoading(true)
    client.json<Saved>(`/questionnaires/${selectedId}`, { signal: controller.signal })
      .then(setSaved).catch(cause => { if (!controller.signal.aborted) setError(message(cause)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [client, selectedId])
  return <>{canImport ? <WorkbookImport client={client} onImported={() => { setSelectedId(null); setOffset(0); setRefresh(value => value + 1) }} /> : <p>Import requires an author or admin role. Open a saved questionnaire to review it.</p>}<section className="task-card" aria-label="Saved questionnaires" aria-busy={loading}>
    <button className="secondary-button" onClick={() => { setSelectedId(null); setRefresh(value => value + 1) }} disabled={loading}>Refresh questionnaires</button>
    {loading && <p role="status">Loading questionnaires…</p>}
    {error && <p role="alert">{error}</p>}
    {listing && <><p>{listing.total} saved questionnaires</p>{listing.items.length === 0 ? <p>No questionnaires on this page. Import a workbook above to get started.</p> : <div className="table-scroll"><table><thead><tr><th>Workbook</th><th>Status</th><th>Items</th><th>Created</th><th>Action</th></tr></thead><tbody>{listing.items.map(row => <tr key={row.id}><td>{row.filename}</td><td>{row.status}</td><td>{row.total}</td><td>{new Date(row.created_at).toLocaleString()}</td><td><button className="secondary-button" disabled={loading} onClick={() => { setFilename(row.filename); setSelectedId(row.id) }}>Open {row.filename}</button></td></tr>)}</tbody></table></div>}
    <div className="pagination"><button disabled={loading || offset === 0} onClick={() => { setSelectedId(null); setOffset(Math.max(0, offset - 20)) }}>Previous page</button><span>Page {offset / 20 + 1}</span><button disabled={loading || listing.next_offset === null} onClick={() => { setSelectedId(null); setOffset(listing.next_offset!) }}>Next page</button></div></>}
    {saved && <section aria-label="Opened questionnaire"><h3>{filename}</h3><p>{saved.total} items · {saved.status}</p><p>Saved questionnaire: {saved.id}</p><p>Workbook mapping is saved. Open the review workspace to draft and check answers.</p>{onReview && <button className="primary-button" onClick={() => onReview({ id: saved.id, filename })}>Review answers</button>}</section>}
  </section></>
}

export function EvidenceEntry({ client }: { client: ApiClient }) {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [version, setVersion] = useState('')
  const [expiry, setExpiry] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  useEffect(() => { return () => { request.current?.abort() } }, [])
  const request = useRef<AbortController | null>(null)
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setResult('')
    if (!title.trim() || !content.trim() || !version.trim() || !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) { setError('Enter a title, plain text, version and valid expiry date.'); return }
    setBusy(true)
    const controller = new AbortController(); request.current = controller
    try {
      const saved = await client.json<{ id: string }>('/documents', { method: 'POST', body: { title: title.trim(), content, version: version.trim(), valid_until: expiry }, signal: controller.signal })
      if (!controller.signal.aborted) { setResult(`Evidence saved: ${title.trim()} (version ${version.trim()}). Document ID: ${saved.id}`); setTitle(''); setContent(''); setVersion(''); setExpiry('') }
    } catch (cause) { if (!controller.signal.aborted) setError(message(cause)) }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  return <section className="task-card"><h3>Legacy text evidence entry</h3><p>Add synthetic plain-text evidence for the connected tenant. Version uploads, revocation and evidence approval arrive in T07. Expired evidence cannot support approved answers.</p>
    <form onSubmit={submit} aria-busy={busy}><fieldset disabled={busy}><label htmlFor="evidence-title">Title</label><input id="evidence-title" required maxLength={300} value={title} onChange={event => setTitle(event.target.value)} />
    <label htmlFor="evidence-content">Plain text</label><textarea id="evidence-content" required maxLength={100000} rows={9} value={content} onChange={event => setContent(event.target.value)} />
    <label htmlFor="evidence-version">Version</label><input id="evidence-version" required maxLength={100} value={version} onChange={event => setVersion(event.target.value)} />
    <label htmlFor="evidence-expiry">Expiry date</label><input id="evidence-expiry" type="date" required value={expiry} onChange={event => setExpiry(event.target.value)} />
    <button className="primary-button" type="submit">{busy ? 'Saving evidence…' : 'Save evidence'}</button></fieldset></form>
    {error && <p role="alert">{error}</p>}{result && <p role="status">{result}</p>}
  </section>
}
