import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiClient } from './api'
import { WorkflowControls } from './WorkflowControls'
afterEach(cleanup)
const response=(data:unknown)=>new Response(JSON.stringify(data))
const job={id:'job',status:'awaiting_review',phase:'human_review',failure_code:null,published_revision:1,review_decision:'pending',attempts:2,input_tokens_reserved:1000,output_tokens_reserved:8000,cost_usd_reserved:'0',steps:[{sequence:1,phase:'classify',status:'done'}]}
const session={tenant:'a',mode:'fixture',authentication:'oidc',roles:['author'],identity_verified:true}
it('runs bounded drafting and leaves approval to the review workspace',async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValueOnce(response({items:[]})).mockResolvedValueOnce(response({...job,status:'queued'})).mockResolvedValueOnce(response(job))
  const changed=vi.fn().mockResolvedValue(undefined)
  render(<WorkflowControls client={new ApiClient('token',fetcher,{oidc:true,tenant:'a'})} itemId="item" revision={0} session={session} disabled={false} onActive={vi.fn()} onChanged={changed} />)
  fireEvent.click(screen.getByRole('button',{name:'Agent workflow'}))
  await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('button',{name:'Start bounded workflow'}))
  expect(await screen.findByText(/Waiting for human review/)).toBeTruthy()
  expect(screen.queryByRole('button',{name:/Approve/})).toBeNull()
  expect(changed).toHaveBeenCalledOnce()
  const body=JSON.parse(String(fetcher.mock.calls[1][1]?.body))
  expect(body.options.max_attempts).toBe(4);expect(body.options.max_cost_usd).toBe(0)
})
it('shows durable reviewer progress without author controls',async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValue(response({items:[job]}))
  render(<WorkflowControls client={new ApiClient('token',fetcher)} itemId="item" revision={1} session={{...session,roles:['reviewer']}} disabled={false} onActive={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(screen.getByRole('button',{name:'Agent workflow'}))
  expect(await screen.findByText(/Waiting for human review/)).toBeTruthy()
  expect(screen.queryByRole('button',{name:'Start bounded workflow'})).toBeNull()
  expect(screen.queryByRole('button',{name:'Cancel workflow'})).toBeNull()
})
it('retains the request key and body when job creation response is lost',async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValueOnce(response({items:[]})).mockRejectedValueOnce(new Error('Lost response')).mockResolvedValueOnce(response({...job,status:'queued'})).mockResolvedValueOnce(response(job))
  render(<WorkflowControls client={new ApiClient('token',fetcher)} itemId="item" revision={0} session={session} disabled={false} onActive={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(screen.getByRole('button',{name:'Agent workflow'}))
  await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('button',{name:'Start bounded workflow'}))
  expect((await screen.findByRole('alert')).textContent).toContain('Reload saved progress')
  fireEvent.click(screen.getByRole('button',{name:'Start bounded workflow'}))
  await screen.findByText(/Waiting for human review/)
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body)
})
