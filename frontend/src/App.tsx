import { EvidenceManager } from './EvidenceManager'
import { ReviewWorkspace, type ReviewSelection } from './ReviewWorkspace'
import { Dashboard, EvidenceEntry } from './TaskTwo'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiClient, ApiError, type Session } from './api'

const pages = {
  questionnaires: { name: 'Questionnaires', icon: '▤', title: 'Your questionnaire workspace', description: 'Bring questions, supporting evidence and approved responses together.' },
  evidence: { name: 'Evidence', icon: '◇', title: 'Answers start with evidence', description: 'Keep the policy text that supports your questionnaire responses close at hand.' },
  review: { name: 'Review', icon: '✓', title: 'Make every answer reviewable', description: 'Check source quotes, refine drafts and approve the current answer revision.' },
}
type Page = keyof typeof pages
type Phase = 'disconnected' | 'connecting' | 'connected' | 'error'

export default function App({ autoConnect = true, oidc = import.meta.env.VITE_AUTH_MODE === 'oidc' }: { autoConnect?: boolean; oidc?: boolean }) {
  const [page, setPage] = useState<Page>('questionnaires')
  const [reviewSelection, setReviewSelection] = useState<ReviewSelection | null>(null)
  const [key, setKey] = useState('')
  const [tenantId, setTenantId] = useState(import.meta.env.VITE_DEFAULT_TENANT || '')
  const [phase, setPhase] = useState<Phase>('disconnected')
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState('')
  const client = useRef<ApiClient | null>(null)
  const pending = useRef<AbortController | null>(null)
  const attempt = useRef(0)
  const input = useRef<HTMLInputElement>(null)
  const selected = pages[page]

  function disconnect() {
    attempt.current += 1
    pending.current?.abort()
    pending.current = null
    client.current?.disconnect()
    client.current = null
    setKey(''); setSession(null); setReviewSelection(null); setError(''); setPhase('disconnected')
    input.current?.focus()
  }
  useEffect(() => {
    if (autoConnect && !oidc) void establishConnection()
    return () => { attempt.current += 1; pending.current?.abort(); client.current?.disconnect() }
  }, [autoConnect, oidc])

  async function connect(event: FormEvent) {
    event.preventDefault()
    if (!key.trim()) return
    await establishConnection(key.trim())
  }

  async function establishConnection(manualKey?: string) {
    const current = ++attempt.current
    pending.current?.abort()
    client.current?.disconnect()
    const controller = new AbortController()
    pending.current = controller
    const candidate = new ApiClient(manualKey || '', undefined, { oidc, tenant: tenantId, onDenied: () => { setSession(null); setReviewSelection(null); setPhase('error'); setError('Session authorization changed. Reconnect with current membership.') } })
    client.current = candidate
    setKey(''); setSession(null); setReviewSelection(null); setError(''); setPhase('connecting')
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    try {
      const connected = await (manualKey ? candidate.connect(controller.signal) : candidate.autoConnect(controller.signal))
      if (current === attempt.current) { setSession(connected); setPhase('connected') }
    } catch (cause) {
      candidate.disconnect()
      if (current === attempt.current) {
        client.current = null
        setPhase('error')
        setError(cause instanceof ApiError ? cause.message : 'Connection timed out. Check the backend and try again.')
      }
    } finally {
      window.clearTimeout(timeout)
      if (current === attempt.current) pending.current = null
    }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to workspace</a>
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage('questionnaires') }} aria-label="EvidenceDesk home"><span className="brand-mark">e<span>·</span></span><span>Evidence<span className="brand-light">Desk</span></span></a>
      <div className="workspace-label"><span className="workspace-icon">ED</span><div>Local workspace<small>Synthetic data · Development</small></div></div>
      <p className="nav-label">WORKSPACE</p>
      <nav aria-label="Workspace">{(Object.keys(pages) as Page[]).map((id) => <button key={id} aria-current={page === id ? 'page' : undefined} onClick={() => setPage(id)}><span aria-hidden="true" className="nav-icon">{pages[id].icon}</span>{pages[id].name}{page === id && <span className="nav-dot" />}</button>)}</nav>
      <div className="sidebar-note"><span className="note-icon" aria-hidden="true">✧</span><strong>Evidence, then confidence.</strong><p>Source-backed drafts.<br />Human-approved answers.</p></div>
      <div className="sidebar-footer"><span className={`status-dot ${phase === 'connected' ? 'online' : ''}`} /><span>{phase === 'connected' ? 'API connected' : 'API not connected'}</span><span className="version">v0.1</span></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div><span className="breadcrumb">Workspace</span><span className="slash">/</span><span>{selected.name}</span></div><span className="local-badge"><span aria-hidden="true">◉</span> Local development</span></header>
      <main id="main" tabIndex={-1}>
        <div className="page-heading"><div><p className="eyebrow">A WORKSPACE BUILT ON EVIDENCE</p><h1>{selected.title}</h1><p className="intro">{selected.description}</p></div><span className="foundation-badge">Local prototype</span></div>
        <section className={`connection-card ${phase === 'connected' ? 'is-connected' : ''}`} aria-labelledby="connection-heading" aria-busy={phase === 'connecting'}>
          <div className="connection-symbol" aria-hidden="true">{phase === 'connected' ? '✓' : '↗'}</div>
          <div className="connection-content">
            <div className="connection-title"><h2 id="connection-heading">{phase === 'connected' ? 'Your workspace is connected' : 'Connect your local API'}</h2><span className={`connection-pill ${phase}`} role="status">{phase === 'connected' ? 'Connected' : phase === 'connecting' ? 'Checking connection…' : phase === 'error' ? 'Connection failed' : 'Not connected'}</span></div>
            {session ? <><p>Connected to <strong>{session.tenant}</strong>. {oidc ? `Verified identity: ${session.subject}. Roles: ${session.roles?.join(', ')}.` : 'Your API key is held only for this session.'}</p><div className="session-details"><span>✓ API health checked</span><span>✓ Key authenticated</span><span>Extractive baseline</span></div><button className="secondary-button" onClick={disconnect}>Disconnect and clear key</button></> : <>
              <p>{oidc ? 'Connect using an API access token from your identity provider. Credentials remain in memory.' : 'Connect automatically to your local backend. Your key stays in memory and is reacquired after a refresh.'}</p>
              {!oidc && <button className="secondary-button" type="button" onClick={() => void establishConnection()} disabled={phase === 'connecting'}>Connect automatically</button>}
              <p className="field-help">{oidc ? 'Use an API audience access token, not an ID token. Local recovery is disabled.' : 'If automatic connection is unavailable, you can use an API key below.'}</p>
              <form onSubmit={connect}><label htmlFor="api-key">{oidc ? 'Access token' : 'API key'}</label>{oidc && <><label htmlFor="tenant-id">Tenant</label><input id="tenant-id" required value={tenantId} onChange={event => setTenantId(event.target.value)} /></>}<div className="key-controls"><input ref={input} id="api-key" type="password" name="api-key" value={key} onChange={(event) => setKey(event.target.value)} autoComplete="off" spellCheck={false} placeholder="Paste your local API key" aria-describedby="key-help" required disabled={phase === 'connecting'} /><button className="primary-button" type="submit" disabled={!key.trim() || phase === 'connecting'}>{phase === 'connecting' ? 'Connecting…' : 'Connect workspace'}<span aria-hidden="true">→</span></button>{phase === 'connecting' && <button className="text-button" type="button" onClick={disconnect}>Cancel</button>}</div><p className="field-help" id="key-help">{oidc ? 'The backend verifies your token and checks current tenant membership.' : 'Use the key from your backend setup or the direct local key-recovery API.'}</p></form>
              {error && <div className="error-message" role="alert"><strong>Could not connect.</strong> {error}</div>}
            </>}
          </div>
        </section>
        <div className="section-heading"><h2>{selected.name}</h2><span className="planned-label">{page === 'review' ? 'T04' : page === 'questionnaires' ? 'T03' : 'T02'}</span></div>
        {page === 'questionnaires' ? (session && client.current ? <Dashboard key={attempt.current} canImport={!oidc || !!session.roles?.some(role => ['author','admin'].includes(role))} client={client.current} onReview={selection => { setReviewSelection(selection); setPage('review') }} /> : <p>Connect to load saved questionnaires.</p>) : page === 'evidence' ? (session && client.current ? <>{oidc ? <EvidenceManager key={attempt.current} client={client.current} session={session} /> : <EvidenceEntry key={attempt.current} client={client.current} />}</> : <p>Connect to add evidence.</p>) : (!session ? <p>Connect to review answers.</p> : !reviewSelection ? <section className="task-card"><h3>Choose a questionnaire to review</h3><p>Open a saved questionnaire, then select Review answers.</p><button className="secondary-button" onClick={() => setPage('questionnaires')}>Go to questionnaires</button></section> : null)}
        {session && client.current && reviewSelection && <div hidden={page !== 'review'}><ReviewWorkspace key={`${attempt.current}:${reviewSelection.id}`} client={client.current} selection={reviewSelection} session={session} /></div>}
        <section className="workflow" aria-label="Questionnaire workflow">{[{number:'01', title:'Bring your questions', detail:'Upload a workbook and map its cells.'}, {number:'02', title:'Ground each answer', detail:'Draft from your supporting evidence.'}, {number:'03', title:'Review, then export', detail:'Approve responses before sharing.'}].map((step) => <div key={step.number}><span className="step-number">{step.number}</span><div><h3>{step.title}</h3><p>{step.detail}</p></div></div>)}</section>
        <footer className="main-footer"><span>EvidenceDesk · Local prototype</span><span>Current drafting uses evidence extraction. Human review remains required.</span></footer>
      </main>
    </div>
  </div>
}
