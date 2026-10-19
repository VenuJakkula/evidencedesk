import { useEffect, useRef, useState } from 'react'
import { ApiClient, ApiError, type Session } from './api'

type Job = {
  id: string; status: string; phase: string; failure_code: string | null; published_revision: number | null
  review_decision: string | null; can_advance?: boolean; attempts: number; input_tokens_reserved: number; output_tokens_reserved: number; cost_usd_reserved: string
  steps: { sequence: number; phase: string; status: string }[]
  owner_task?: { owner: string; reason: string } | null
}
const stopped = (job: Job) => ['awaiting_review','owner_task','failed','cancelled','completed','retryable'].includes(job.status)
const labels: Record<string, string> = { queued: 'Ready to start', running: 'In progress', retryable: 'Retry needs your action', awaiting_review: 'Waiting for human review', owner_task: 'Needs evidence and an owner', failed: 'Stopped', cancelled: 'Cancelled', completed: 'Human review completed' }

export function WorkflowControls({ client, itemId, revision, session, disabled, onActive, onChanged }: {
  client: ApiClient; itemId: string; revision: number; session: Session; disabled: boolean
  onActive: (active: boolean) => void; onChanged: (signal: AbortSignal) => Promise<void>
}) {
  const canAuthor = !!session.roles?.some(role => ['author','admin'].includes(role))
  const [open, setOpen] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deadline, setDeadline] = useState(120)
  const [attempts, setAttempts] = useState(4)
  const [input, setInput] = useState(100000)
  const [output, setOutput] = useState(16000)
  const [cost, setCost] = useState(0)
  const cancellationConfirmed = useRef(false)
  const requestKey = useRef<string | null>(null)
  const requestBody = useRef<unknown>(null)
  const action = useRef<AbortController | null>(null)
  const callbacks = useRef({ onActive, onChanged }); callbacks.current = { onActive, onChanged }
  useEffect(() => () => { action.current?.abort(); callbacks.current.onActive(false) }, [])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void client.json<{ items: Job[] }>(`/workflow-jobs?item_id=${encodeURIComponent(itemId)}&limit=5`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setJob(result.items[0] || null) })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load workflow jobs.') })
    return () => controller.abort()
  }, [client, itemId, open])

  async function operate(operation: (signal: AbortSignal) => Promise<void>) {
    if (action.current) return
    const controller = new AbortController(); action.current = controller
    cancellationConfirmed.current = false; setBusy(true); setError(''); callbacks.current.onActive(true)
    const timeout = window.setTimeout(() => controller.abort(), 180000)
    try { await operation(controller.signal) }
    catch (cause) { if (cancellationConfirmed.current) return; if (cause instanceof ApiError && [400,401,403,404,409,422].includes(cause.status)) { requestKey.current = null; requestBody.current = null } if (!controller.signal.aborted) setError(cause instanceof Error ? `${cause.message} Reload saved progress before continuing.` : 'Request failed. Reload saved progress.'); else setError('Request interrupted. Reload saved progress; use Cancel workflow to stop server work.') }
    finally { window.clearTimeout(timeout); setBusy(false); action.current = null; callbacks.current.onActive(false) }
  }
  async function run(current: Job, signal: AbortSignal) {
    for (let step = 0; step < 12; step++) {
      current = await client.json<Job>(`/workflow-jobs/${current.id}/advance`, { method: 'POST', signal })
      if (signal.aborted) return
      setJob(current)
      if (stopped(current)) break
    }
    if (current.published_revision) await callbacks.current.onChanged(signal)
  }
  function start() {
    void operate(async signal => {
      if (!requestKey.current) {
        requestKey.current = crypto.randomUUID()
        requestBody.current = { item_id: itemId, expected_revision: revision, request_key: requestKey.current, options: { deadline_seconds: deadline, max_attempts: attempts, max_input_tokens: input, max_output_tokens: output, max_cost_usd: cost } }
      }
      const created = await client.json<Job>('/workflow-jobs', { method: 'POST', body: requestBody.current, signal })
      requestKey.current = null; requestBody.current = null
      if (signal.aborted) return
      setJob(created); await run(created, signal)
    })
  }
  function refresh() {
    void operate(async signal => {
      const result = await client.json<{ items: Job[] }>(`/workflow-jobs?item_id=${encodeURIComponent(itemId)}&limit=5`, { signal })
      if (signal.aborted) return
      const latest = result.items[0] || null; setJob(latest)
      if (latest?.published_revision) await callbacks.current.onChanged(signal)
    })
  }
  async function cancel() {
    if (!job) return
    try {
      const current = await client.json<Job>(`/workflow-jobs/${job.id}/cancel`, { method: 'POST' })
      cancellationConfirmed.current = true; action.current?.abort(); setBusy(false); setJob(current); setError('')
      const controller = new AbortController(); await callbacks.current.onChanged(controller.signal)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Cancellation could not be confirmed. Reload saved progress.') }
  }
  const active = job && !['completed','owner_task','failed','cancelled'].includes(job.status)
  return <section aria-label="Agent workflow" className="workflow-panel">
    <button className="secondary-button" aria-expanded={open} onClick={() => setOpen(value => !value)}>Agent workflow</button>
    {open && <>
      <p>Bounded drafting saves an unapproved revision. Review its claims and citations before using Approve revision.</p>
      {canAuthor && <fieldset disabled={busy || disabled || !!active || requestKey.current !== null}><legend>Workflow limits</legend>
        <label>Deadline (seconds)<input type="number" min={5} max={300} value={deadline} onChange={event => setDeadline(Number(event.target.value))} /></label>
        <label>Provider attempt limit<input type="number" min={1} max={6} value={attempts} onChange={event => setAttempts(Number(event.target.value))} /></label>
        <label>Input token budget (conservative)<input type="number" min={100} max={1000000} value={input} onChange={event => setInput(Number(event.target.value))} /></label>
        <label>Output token budget (conservative)<input type="number" min={100} max={64000} value={output} onChange={event => setOutput(Number(event.target.value))} /></label>
        <label>Authorized cost limit (USD)<input type="number" min={0} max={100} step={0.01} value={cost} onChange={event => setCost(Number(event.target.value))} /></label>
      </fieldset>}
      <div className="review-actions">
        {canAuthor && <button className="primary-button" disabled={busy || disabled || !!active} onClick={start}>Start bounded workflow</button>}
        <button className="secondary-button" disabled={busy} onClick={refresh}>Reload saved progress</button>
        {canAuthor && active && job.can_advance !== false && <button className="secondary-button" disabled={busy || disabled || (job.status === 'awaiting_review' && job.review_decision !== 'approved')} onClick={() => void operate(signal => run(job, signal))}>{job.status === 'awaiting_review' ? 'Finish reviewed workflow' : job.status === 'retryable' ? 'Retry bounded step' : 'Continue workflow'}</button>}
        {canAuthor && active && job.can_advance !== false && <button className="secondary-button" onClick={() => void cancel()}>Cancel workflow</button>}
      </div>
      {job && <div role="status"><p>{labels[job.status] || job.status}. Last phase: {job.phase.replaceAll('_', ' ')}. {job.published_revision && `Published revision ${job.published_revision}.`} {job.review_decision && `Human review: ${job.review_decision}.`}</p>
        <p>{job.attempts} provider attempts · Reserved input/output units: {job.input_tokens_reserved}/{job.output_tokens_reserved} · Reserved cost: ${job.cost_usd_reserved}</p>
        <ol>{job.steps.map(step => <li key={step.sequence}>{step.phase.replaceAll('_', ' ')}: {step.status}</li>)}</ol>
        {job.failure_code && <p>Reason: {job.failure_code}</p>}
        {job.owner_task && <p>Owner task: {job.owner_task.owner}. Add approved evidence or assign a subject-matter expert.</p>}
      </div>}
      {busy && <p role="status">Advancing bounded workflow…</p>}
      {error && <p role="alert" className="error-message">{error}</p>}
    </>}
  </section>
}
