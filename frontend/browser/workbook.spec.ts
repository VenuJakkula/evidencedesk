import { expect, test, type Page } from './fixtures'
import { resolve } from 'node:path'
const sample = (kind: string) => resolve(import.meta.dirname, '../../samples', `${kind}.xlsx`)
async function connect(page: Page) {
  await page.goto('/')
  await expect(page.getByText('Your workspace is connected')).toBeVisible()
}
async function inspect(page: Page, kind = 'security') {
  await page.getByLabel('Workbook (.xlsx)').setInputFiles(sample(kind))
  await page.getByRole('button', { name: 'Inspect workbook', exact: true }).click()
  await expect(page.getByLabel(`Map ${kind === 'rfp' ? 'RFP' : 'Security'}`, { exact: true })).toBeVisible()
}
async function mapSheet(page: Page, sheet: string, header: string, question: string, answer: string, identifier = '') {
  await page.getByLabel(`Map ${sheet}`, { exact: true }).check()
  await page.getByLabel(`Header row for ${sheet}`, { exact: true }).fill(header)
  await page.getByLabel(`Question column for ${sheet}`, { exact: true }).fill(question)
  await page.getByLabel(`Answer column for ${sheet}`, { exact: true }).fill(answer)
  if (identifier) await page.getByLabel(`Identifier column for ${sheet} (optional)`, { exact: true }).fill(identifier)
}
async function explicitMapping(page: Page, kind: string) {
  await mapSheet(page, kind === 'rfp' ? 'RFP' : 'Security', kind === 'rfp' ? '3' : '1', 'B', 'C', 'A')
  await mapSheet(page, 'Operations', '1', 'A', 'B')
}
async function apiHeaders(page: Page) {
  const response = await page.request.post('/dev/session-key', { headers: { 'X-Local-Session': 'true', Origin: new URL(page.url()).origin } })
  expect(response.ok()).toBe(true)
  const body = await response.json()
  return { 'X-API-Key': body.api_key as string }
}
for (const kind of ['security', 'rfp']) {
  test(`${kind} imports five items through explicit browser mappings and reopens after refresh`, async ({ page }) => {
    await connect(page); await inspect(page, kind)
    const sheet = kind === 'rfp' ? 'RFP' : 'Security'
    await expect(page.getByLabel(`Map ${sheet}`, { exact: true })).not.toBeChecked()
    await expect(page.getByRole('button', { name: 'Confirm import', exact: true })).toHaveCount(0)
    await explicitMapping(page, kind)
    await expect(page.getByLabel(`Allow overwriting existing answers for ${sheet}`, { exact: true })).not.toBeChecked()
    await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
    await expect(page.getByText('5 questions total. Showing 5 rows.', { exact: true })).toBeVisible()
    const header = kind === 'rfp' ? 3 : 1
    for (const row of [header + 1, header + 2, header + 4, header + 5]) {
      await expect(page.getByRole('cell', { name: `${sheet}!B${row}`, exact: true })).toBeVisible()
      await expect(page.getByRole('cell', { name: `${sheet}!C${row}`, exact: true })).toBeVisible()
    }
    await expect(page.getByRole('cell', { name: 'Operations!A2', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Operations!B2', exact: true })).toBeVisible()
    await expect(page.getByText(/Existing answer preserved; this destination/)).toBeVisible()
    await expect(page.getByText(/Hidden row skipped/)).toBeVisible()
    await page.getByRole('button', { name: 'Confirm import', exact: true }).click()
    await expect(page.getByText('Workbook imported', { exact: true })).toBeVisible()
    const idText = await page.getByText(/^Questionnaire ID:/).innerText()
    const id = idText.replace('Questionnaire ID: ', '')
    const headers = await apiHeaders(page)
    const response = await page.request.get(`/api/questionnaires/${id}/items`, { headers })
    const items = await response.json()
    expect(items.total).toBe(5)
    expect(items.items.map((item: { provenance: { sheet: string; question_cell: string; answer_cell: string } }) => [item.provenance.sheet, item.provenance.question_cell, item.provenance.answer_cell])).toEqual([
      ...[header + 1, header + 2, header + 4, header + 5].map(row => [sheet, `B${row}`, `C${row}`]), ['Operations', 'A2', 'B2'],
    ])
    await page.reload(); await expect(page.getByText('Your workspace is connected')).toBeVisible()
    await page.getByRole('button', { name: `Open ${kind}.xlsx`, exact: true }).click()
    await expect(page.getByText(`Saved questionnaire: ${id}`, { exact: true })).toBeVisible()
    expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 })
  })
}

test('mapping errors, hidden intent and overwrite warnings require user choices', async ({ page }) => {
  await connect(page); await inspect(page)
  await mapSheet(page, 'Security', '1', 'B', 'B')
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('invalid_mapping')
  await page.getByLabel('Answer column for Security', { exact: true }).fill('C')
  await page.getByLabel('Allow overwriting existing answers for Security', { exact: true }).check()
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByText(/Existing answer may be overwritten/)).toBeVisible()
  await page.getByLabel('Allow overwriting existing answers for Security', { exact: true }).uncheck()
  await expect(page.getByText('Mapped preview', { exact: true })).toHaveCount(0)
  await page.getByLabel('Map Security', { exact: true }).uncheck()
  await mapSheet(page, 'Internal', '1', 'A', 'B')
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('hidden_sheet')
  await page.getByLabel('Include hidden rows and sheets for Internal', { exact: true }).check()
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByText('Mapped preview', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Internal!A2', exact: true })).toBeVisible()
})

test('unsupported files and server upload limits are displayed', async ({ page }) => {
  await connect(page)
  await page.getByLabel('Workbook (.xlsx)').setInputFiles({ name: 'legacy.xlsm', mimeType: 'application/octet-stream', buffer: Buffer.from('unsupported') })
  await expect(page.getByRole('alert')).toContainText('unsupported_format')
  await page.getByLabel('Workbook (.xlsx)').setInputFiles({ name: 'malformed.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('malformed') })
  await page.getByRole('button', { name: 'Inspect workbook', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('malformed_workbook')
  await page.getByLabel('Workbook (.xlsx)').setInputFiles({ name: 'oversized.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.alloc(10 * 1024 * 1024 + 65537) })
  await page.getByRole('button', { name: 'Inspect workbook', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('upload_too_large')
})

test('lost import response retries the committed payload with the same key; conflict is visible', async ({ page }) => {
  await connect(page); await inspect(page); await explicitMapping(page, 'security')
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByText('Mapped preview', { exact: true })).toBeVisible()
  const keys: string[] = []
  let committedId = ''
  page.on('request', request => {
    if (request.url().endsWith('/api/questionnaires') && request.method() === 'POST') keys.push(request.headers()['idempotency-key'])
  })
  // Fail the genuine browser response after the server commits, preserving the original multipart bytes.
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/questionnaires', requestStage: 'Response' }] })
  cdp.on('Fetch.requestPaused', async event => {
    if (event.request.method === 'POST' && event.responseStatusCode === 201 && !committedId) {
      const response = await cdp.send('Fetch.getResponseBody', { requestId: event.requestId })
      committedId = JSON.parse(response.base64Encoded ? Buffer.from(response.body, 'base64').toString('utf8') : response.body).id
      await cdp.send('Fetch.failRequest', { requestId: event.requestId, errorReason: 'Failed' })
      await cdp.send('Fetch.disable')
    } else await cdp.send('Fetch.continueRequest', { requestId: event.requestId })
  })
  await page.getByRole('button', { name: 'Confirm import', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('network_error')
  await page.getByRole('button', { name: 'Confirm import', exact: true }).click()
  await expect(page.getByText(`Questionnaire ID: ${committedId}`, { exact: true })).toBeVisible()
  expect(keys.length).toBe(2); expect(keys[0]).toBeTruthy(); expect(keys[1]).toBe(keys[0])
  const headers = await apiHeaders(page)
  const listing = await (await page.request.get('/api/questionnaires', { headers })).json()
  expect(listing.items.filter((item: { id: string }) => item.id === committedId)).toHaveLength(1)
  await cdp.detach()
  await page.getByRole('button', { name: 'Start another import', exact: true }).click()
  await inspect(page); await explicitMapping(page, 'security')
  await page.getByRole('button', { name: 'Preview mapped questions', exact: true }).click()
  await expect(page.getByText('Mapped preview', { exact: true })).toBeVisible()
  await page.route('**/api/questionnaires', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'idempotency_conflict', message: 'This key was used for a different payload.' } }) })
    } else await route.continue()
  })
  await page.getByRole('button', { name: 'Confirm import', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('idempotency_conflict')
  await expect(page.getByRole('alert')).toContainText('Start another import')
  expect(keys[2]).not.toBe(keys[0])
})
