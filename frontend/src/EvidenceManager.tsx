import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiClient, ApiError, type Session } from './api'
type Source = { id: string; title: string; can_write: boolean; current_version: string; versions: { id: string; label: string; content: string; valid_until: string; state: string; metadata: Record<string,string> }[] }
type Listing = { items: { id: string; title: string; label: string; state: string }[]; next_offset: number | null; total: number }
export function EvidenceManager({ client, session }: { client: ApiClient; session: Session }) {
  const [listing,setListing]=useState<Listing|null>(null)
  const [source,setSource]=useState<Source|null>(null)
  const [offset,setOffset]=useState(0)
  const [refresh,setRefresh]=useState(0)
  const [title,setTitle]=useState('')
  const [content,setContent]=useState('')
  const [version,setVersion]=useState('')
  const [expiry,setExpiry]=useState('')
  const [product,setProduct]=useState('')
  const [edition,setEdition]=useState('')
  const [deployment,setDeployment]=useState('')
  const [provenance,setProvenance]=useState('')
  const [file,setFile]=useState<File|null>(null)
  const [subject,setSubject]=useState('')
  const [canWrite,setCanWrite]=useState(false)
  const [memberRoles,setMemberRoles]=useState(['author'])
  const [active,setActive]=useState(true)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const pending=useRef<AbortController|null>(null)
  const admin=!!session.roles?.includes('admin')
  const author=admin||!!session.roles?.includes('author')
  const reviewer=admin||!!session.roles?.includes('reviewer')
  useEffect(()=>()=>pending.current?.abort(),[])
  useEffect(()=>{
    const controller=new AbortController()
    client.json<Listing>(`/evidence?offset=${offset}&limit=20`,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setListing(value)}).catch(cause=>{if(!controller.signal.aborted)setError(cause.message)})
    return()=>controller.abort()
  },[client,offset,refresh])
  async function run(operation:(signal:AbortSignal)=>Promise<void>){
    if(pending.current)return
    const controller=new AbortController();pending.current=controller;setBusy(true);setError('');setNotice('')
    try{await operation(controller.signal)}catch(cause){if(!controller.signal.aborted){setError(cause instanceof Error?cause.message:'Request failed');if(cause instanceof ApiError&&[401,403,404].includes(cause.status)){setSource(null);setTitle('');setContent('')}}}finally{if(pending.current===controller){pending.current=null;setBusy(false)}}
  }
  async function save(event:FormEvent){
    event.preventDefault()
    await run(async signal=>{
      const metadata={product,edition,deployment,provenance}
      let result:Source
      if(source) result=await client.json<Source>(`/evidence/${source.id}/versions`,{method:'POST',signal,body:{expected_version:source.current_version,content,version,valid_until:expiry,metadata}})
      else if(file){
        const form=new FormData();form.append('file',file);form.append('metadata',JSON.stringify({title,version,valid_until:expiry,metadata}))
        result=await client.upload<Source>('/evidence/upload',form,undefined,signal)
      }else result=await client.json<Source>('/evidence',{method:'POST',signal,body:{title,content,version,valid_until:expiry,metadata}})
      if(signal.aborted)return
      setSource(result);setFile(null);setRefresh(value=>value+1);setNotice('Immutable version saved as pending. Explicit evidence approval is required before drafting.')
    })
  }
  function select(id:string){void run(async signal=>{const result=await client.json<Source>(`/evidence/${id}`,{signal});if(!signal.aborted){setSource(result);setTitle(result.title);setContent('');setVersion('');setExpiry('');setFile(null)}})}
  function action(path:string,method='POST',body?:unknown){void run(async signal=>{
    await client.json(path,{method,body,signal});if(signal.aborted)return
    setRefresh(value=>value+1);setNotice('Change saved. Reload review items to see current evidence/access state.')
    if(source&&method!=='DELETE'){const result=await client.json<Source>(`/evidence/${source.id}`,{signal});if(!signal.aborted)setSource(result)}else setSource(null)
  })}
  return <section className="task-card" aria-label="Evidence lifecycle"><h2>Approved evidence versions</h2><p>Only current approved, unexpired versions you can access support drafts. Source changes, revocation or deletion invalidate dependent approvals. Deleted sources are tombstoned; immutable history and audit records remain retained.</p>
    <button className="secondary-button" disabled={busy} onClick={()=>{setSource(null);setTitle('');setContent('');setVersion('');setExpiry('');setFile(null)}}>New evidence source</button>
    {error&&<p role="alert" className="error-message">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {listing&&<><p>{listing.total} accessible sources</p><ul>{listing.items.map(row=><li key={row.id}><button className="secondary-button" disabled={busy} onClick={()=>select(row.id)}>Open evidence {row.title}</button> Version {row.label} · {row.state}</li>)}</ul><div className="pagination"><button disabled={!offset||busy} onClick={()=>setOffset(Math.max(0,offset-20))}>Previous evidence</button><button disabled={listing.next_offset===null||busy} onClick={()=>setOffset(listing.next_offset!)}>Next evidence</button></div></>}
    {source&&<section aria-label="Evidence history"><h3>{source.title}</h3><p>Source ID: {source.id}</p>{source.versions.map(item=><details key={item.id}><summary>Version {item.label} · {item.state} · Expires {item.valid_until}</summary><p className="answer-text">{item.content}</p><p>Product: {item.metadata.product||'Unspecified'} · Edition: {item.metadata.edition||'Unspecified'} · Deployment: {item.metadata.deployment||'Unspecified'}</p><p>Provenance: {item.metadata.provenance||item.metadata.filename||item.metadata.origin||'Unspecified'}</p></details>)}
      {reviewer&&<button className="primary-button" disabled={busy||source.versions[0]?.state!=='pending'} onClick={()=>action(`/evidence/${source.id}/approve`,'POST',{version_id:source.current_version})}>Approve evidence version</button>}
      {admin&&<div className="review-actions"><button disabled={busy} onClick={()=>action(`/evidence/${source.id}/revoke`)}>Revoke evidence source</button><button disabled={busy} onClick={()=>action(`/evidence/${source.id}`,'DELETE')}>Delete source (tombstone)</button></div>}
    </section>}
    {author&&(!source||source.can_write)&&<form onSubmit={save}><fieldset disabled={busy}><legend>{source?'Add an immutable version':'Create an evidence source'}</legend><label htmlFor="source-title">Evidence title</label><input id="source-title" required maxLength={300} value={title} disabled={!!source} onChange={event=>setTitle(event.target.value)}/>
      {!source&&<><label htmlFor="source-file">UTF-8 text file (optional .txt)</label><input id="source-file" type="file" accept=".txt" onChange={event=>setFile(event.target.files?.[0]||null)}/></>}
      <label htmlFor="source-content">Evidence text</label><textarea id="source-content" required={!file} disabled={!!file} rows={6} maxLength={100000} value={content} onChange={event=>setContent(event.target.value)}/>
      <label htmlFor="source-version">Version label</label><input id="source-version" required maxLength={100} value={version} onChange={event=>setVersion(event.target.value)}/>
      <label htmlFor="source-expiry">Evidence expiry</label><input id="source-expiry" type="date" required value={expiry} onChange={event=>setExpiry(event.target.value)}/>
      {[['Product',product,setProduct],['Edition',edition,setEdition],['Deployment',deployment,setDeployment],['Provenance',provenance,setProvenance]].map(([label,value,setter])=><div key={label as string}><label htmlFor={`meta-${label}`}>{label as string}</label><input id={`meta-${label}`} maxLength={300} value={value as string} onChange={event=>(setter as (value:string)=>void)(event.target.value)}/></div>)}
      <button className="primary-button">Save immutable evidence version</button></fieldset></form>}
    {admin&&<section aria-label="Access administration"><h3>Tenant membership and document access</h3><label htmlFor="member-subject">Member subject</label><input id="member-subject" maxLength={200} value={subject} onChange={event=>setSubject(event.target.value)}/>
      <div>{['author','reviewer','admin'].map(role=><label className="check-field" key={role}><input type="checkbox" checked={memberRoles.includes(role)} onChange={event=>setMemberRoles(current=>event.target.checked?[...current,role]:current.filter(value=>value!==role))}/>{role}</label>)}</div>
      <label className="check-field"><input type="checkbox" checked={active} onChange={event=>setActive(event.target.checked)}/>Membership active</label>
      <button disabled={busy||!subject||!memberRoles.length} onClick={()=>action('/memberships','PUT',{subject,roles:memberRoles,active})}>Save tenant membership</button>
      {source&&<><label className="check-field"><input type="checkbox" checked={canWrite} onChange={event=>setCanWrite(event.target.checked)}/>Allow source version writes</label><div className="review-actions"><button disabled={busy||!subject} onClick={()=>action(`/evidence/${source.id}/acl`,'PUT',{subject,can_write:canWrite})}>Grant source access</button><button disabled={busy||!subject} onClick={()=>action(`/evidence/${source.id}/acl`,'DELETE',{subject})}>Revoke source access</button></div></>}
    </section>}
  </section>
}
