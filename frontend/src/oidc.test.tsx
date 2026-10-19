import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ApiClient } from './api'
import App from './App'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const response=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status})
it('uses only bearer authentication and a selected tenant for verified sessions',async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValueOnce(response({status:'ok'})).mockResolvedValueOnce(response({tenant:'a',mode:'extractive-baseline',authentication:'oidc',identity_verified:true,subject:'subject',issuer:'https://issuer.invalid',roles:['author']}))
  const client=new ApiClient('signed-token',fetcher,{oidc:true,tenant:'a'})
  expect((await client.connect()).identity_verified).toBe(true)
  const headers=new Headers(fetcher.mock.calls[1][1]?.headers)
  expect(headers.get('Authorization')).toBe('Bearer signed-token');expect(headers.get('X-Tenant-ID')).toBe('a');expect(headers.has('X-API-Key')).toBe(false)
})
it('clears revoked credentials and never uses local bootstrap in OIDC mode',async()=>{
  const denied=vi.fn();const fetcher=vi.fn<typeof fetch>().mockResolvedValue(response({error:{code:'membership_required',message:'Membership revoked'}},403))
  const client=new ApiClient('signed-token',fetcher,{oidc:true,tenant:'a',onDenied:denied})
  await expect(client.autoConnect()).rejects.toMatchObject({code:'oidc_required'});expect(fetcher).not.toHaveBeenCalled()
  await expect(client.json('/session')).rejects.toMatchObject({status:403});expect(denied).toHaveBeenCalledOnce()
  await expect(client.json('/session')).rejects.toMatchObject({code:'not_connected'})
})
it('deployed frontend omits automatic recovery and accepts a verified bearer session',async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValueOnce(response({status:'ok'})).mockResolvedValueOnce(response({tenant:'a',mode:'extractive-baseline',authentication:'oidc',identity_verified:true,subject:'reviewer',issuer:'https://issuer.invalid',roles:['reviewer']})).mockResolvedValueOnce(response({items:[],total:0,next_offset:null}))
  vi.stubGlobal('fetch',fetcher)
  render(<App oidc />)
  expect(fetcher).not.toHaveBeenCalled();expect(screen.queryByRole('button',{name:'Connect automatically'})).toBeNull()
  fireEvent.change(screen.getByLabelText('Tenant'),{target:{value:'a'}})
  fireEvent.change(screen.getByLabelText('Access token'),{target:{value:'signed-token'}})
  fireEvent.click(screen.getByRole('button',{name:/Connect workspace/}))
  await screen.findByText(/Verified identity: reviewer/)
  expect(fetcher.mock.calls.some(([url])=>String(url).includes('/dev/'))).toBe(false)
  expect(screen.queryByLabelText('Access token')).toBeNull()
})
