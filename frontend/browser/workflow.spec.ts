import { test, expect } from './fixtures'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const tokens = () => JSON.parse(readFileSync(resolve(process.env.EVIDENCEDESK_BROWSER_FIXTURE_DIR!, 'oidc-fixture.json'),'utf8')).tokens as Record<string,string>
const headers = () => ({Authorization:`Bearer ${tokens().admin}`,'X-Tenant-ID':'enterprise'})
test('signed workflow progresses, persists an unapproved revision and resumes after verified human review',async({page})=>{
  await page.goto('/')
  await page.getByLabel('Access token',{exact:true}).fill(tokens().admin)
  await page.getByRole('button',{name:'Connect workspace'}).click()
  await expect(page.getByText('Your workspace is connected')).toBeVisible()
  const response=await page.request.post('/api/evidence',{headers:headers(),data:{title:'Workflow policy',content:'Customer data is encrypted at rest using AES-256.',version:'1',valid_until:'2099-01-01'}})
  const source=await response.json();expect(response.status()).toBe(201)
  expect((await page.request.post(`/api/evidence/${source.id}/approve`,{headers:headers(),data:{version_id:source.current_version}})).status()).toBe(200)
  const imported=await page.request.post('/api/questionnaires',{headers:{...headers(),'Idempotency-Key':crypto.randomUUID()},multipart:{file:{name:'workflow.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:readFileSync(resolve(import.meta.dirname,'../../samples/security.xlsx'))},mapping:readFileSync(resolve(import.meta.dirname,'../../samples/security.mapping.json'),'utf8')}})
  expect(imported.status()).toBe(201)
  const id=(await imported.json()).id
  await page.getByRole('button',{name:'Evidence',exact:true}).click()
  await page.getByRole('button',{name:'Questionnaires',exact:true}).click()
  await page.getByRole('button',{name:'Refresh questionnaires',exact:true}).click()
  await page.getByRole('button',{name:'Open workflow.xlsx',exact:true}).click()
  await page.getByRole('button',{name:'Review answers',exact:true}).click()
  const first=page.locator('.review-item').first()
  await first.getByRole('button',{name:'Agent workflow',exact:true}).click()
  await first.getByRole('button',{name:'Start bounded workflow',exact:true}).click()
  await expect(first.getByText(/Waiting for human review/)).toBeVisible({timeout:45000})
  await expect(first.getByLabel('Answer text',{exact:true})).toHaveValue(/AES-256/)
  const items=(await (await page.request.get(`/api/questionnaires/${id}/items`,{headers:headers()})).json()).items
  expect(items[0].current_revision).toBe(1);expect(items[0].answer.approval).toBeNull()
  await first.getByRole('button',{name:'Approve revision 1',exact:true}).click()
  await first.getByRole('button',{name:'Reload saved progress',exact:true}).click()
  await expect(first.getByText(/Human review: approved/)).toBeVisible()
  await first.getByRole('button',{name:'Finish reviewed workflow',exact:true}).click()
  await expect(first.getByText(/Human review completed/)).toBeVisible()
  const saved=(await (await page.request.get(`/api/questionnaires/${id}/items`,{headers:headers()})).json()).items[0]
  expect(saved.current_revision).toBe(1);expect(saved.answer.approval.identity_verified).toBe(1)
  expect(await page.evaluate(()=>({local:localStorage.length,session:sessionStorage.length}))).toEqual({local:0,session:0})
})
