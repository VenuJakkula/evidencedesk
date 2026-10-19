import { expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
export const encryption = 'Customer data is encrypted at rest using AES-256.'
export async function seedReview(page: Page, name: string, options: { large?: boolean; kind?: 'security' | 'rfp' } = {}) {
  const kind = options.kind || 'security'
  await page.goto('/')
  await expect(page.getByText('Your workspace is connected')).toBeVisible()
  const bootstrap = await page.request.post('/dev/session-key', { headers: { 'X-Local-Session': 'true', Origin: new URL(page.url()).origin } })
  expect(bootstrap.ok()).toBe(true)
  const headers = { 'X-API-Key': (await bootstrap.json()).api_key as string }
  const evidence = await page.request.post('/api/documents', { headers, data: { title: 'Synthetic review policy', content: `${encryption} Transport encryption uses TLS 1.2 or higher.`, version: 'review-v1', valid_until: '2099-01-01' } })
  expect(evidence.status()).toBe(201)
  const mapping = options.large ? { sheets: [{ sheet: 'Questions', header_row: 1, question_column: 'A', answer_column: 'B' }] } : JSON.parse(readFileSync(resolve(import.meta.dirname, `../../samples/${kind}.mapping.json`), 'utf8'))
  const filePath = options.large ? process.env.EVIDENCEDESK_BROWSER_LARGE_WORKBOOK! : resolve(import.meta.dirname, `../../samples/${kind}.xlsx`)
  const filename = `${name}.xlsx`
  const imported = await page.request.post('/api/questionnaires', { headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() }, multipart: { file: { name: filename, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: readFileSync(filePath) }, mapping: JSON.stringify(mapping) } })
  expect(imported.status()).toBe(201)
  const questionnaire = await imported.json()
  await page.getByRole('button', { name: 'Refresh questionnaires', exact: true }).click()
  await page.getByRole('button', { name: `Open ${filename}`, exact: true }).click()
  await page.getByRole('button', { name: 'Review answers', exact: true }).click()
  await expect(page.getByRole('heading', { name: `Review ${filename}`, exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Draft remaining items', exact: true })).toBeEnabled()
  return { headers, id: questionnaire.id as string }
}
export async function draftReview(page: Page) {
  await page.getByRole('button', { name: 'Draft remaining items', exact: true }).click()
  await expect(page.getByText('Drafting complete. All generated answers still require human review.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Reload review page', exact: true })).toBeEnabled()
}
