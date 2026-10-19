import AxeBuilder from '@axe-core/playwright'
import { test, expect, type Page } from './fixtures'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

async function accessibility(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(result.violations.map(violation => ({ id: violation.id, impact: violation.impact,
    nodes: violation.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) }))).toEqual([])
}
async function keyboardActivate(page: Page, button: ReturnType<Page['getByRole']>) {
  await expect(button).toBeEnabled(); await button.focus(); await expect(button).toBeFocused()
  await page.keyboard.press('Enter')
}

for (const kind of ['security', 'rfp'] as const) {
  test(`journey ${kind}: UI connect, evidence, map, draft, edit, approve and real download`, async ({ page }, testInfo) => {
    const external: string[] = []; const errors: string[] = []
    page.on('request', request => { if (request.url().startsWith('http') && new URL(request.url()).origin !== new URL(process.env.EVIDENCEDESK_BROWSER_BASE_URL!).origin) external.push(request.url()) })
    page.on('pageerror', error => errors.push(error.message))
    await page.goto('/')
    await expect(page.getByText('Your workspace is connected')).toBeVisible()
    await page.keyboard.press('Tab'); await expect(page.getByRole('link', { name: 'Skip to workspace' })).toBeFocused()
    await page.keyboard.press('Enter'); await expect(page.getByRole('main')).toBeFocused()
    await accessibility(page)

    await keyboardActivate(page, page.getByRole('button', { name: 'Evidence', exact: true }))
    const title = page.getByLabel('Title', { exact: true })
    await title.focus(); await title.fill('Synthetic journey policy')
    await page.keyboard.press('Tab'); await expect(page.getByLabel('Plain text', { exact: true })).toBeFocused()
    await page.getByLabel('Plain text', { exact: true }).fill('Customer data is encrypted at rest using AES-256. Transport encryption uses TLS 1.2 or higher.')
    await page.keyboard.press('Tab'); await expect(page.getByLabel('Version', { exact: true })).toBeFocused()
    await page.getByLabel('Version', { exact: true }).fill('journey-v1')
    await page.keyboard.press('Tab'); await expect(page.getByLabel('Expiry date', { exact: true })).toBeFocused()
    await page.getByLabel('Expiry date', { exact: true }).fill('2099-01-01')
    await accessibility(page)
    await keyboardActivate(page, page.getByRole('button', { name: 'Save evidence', exact: true }))
    await expect(page.getByText(/Evidence saved: Synthetic journey policy/)).toBeVisible()

    await keyboardActivate(page, page.getByRole('button', { name: 'Questionnaires', exact: true }))
    await page.getByLabel('Workbook (.xlsx)', { exact: true }).setInputFiles(resolve(import.meta.dirname, `../../samples/${kind}.xlsx`))
    await keyboardActivate(page, page.getByRole('button', { name: 'Inspect workbook', exact: true }))
    const sheet = kind === 'security' ? 'Security' : 'RFP'
    const header = kind === 'security' ? 1 : 3
    const checkbox = page.getByLabel(`Map ${sheet}`, { exact: true })
    await expect(checkbox).not.toBeChecked(); await checkbox.focus(); await page.keyboard.press('Space'); await expect(checkbox).toBeChecked()
    await page.getByLabel(`Header row for ${sheet}`, { exact: true }).focus()
    await page.getByLabel(`Header row for ${sheet}`, { exact: true }).fill(String(header))
    await page.keyboard.press('Tab'); await expect(page.getByLabel(`Question column for ${sheet}`, { exact: true })).toBeFocused()
    await page.getByLabel(`Question column for ${sheet}`, { exact: true }).fill('B')
    await page.keyboard.press('Tab'); await expect(page.getByLabel(`Answer column for ${sheet}`, { exact: true })).toBeFocused()
    await page.getByLabel(`Answer column for ${sheet}`, { exact: true }).fill('B')
    await keyboardActivate(page, page.getByRole('button', { name: 'Preview mapped questions', exact: true }))
    await expect(page.getByRole('alert')).toContainText('invalid_mapping')
    await expect(page.getByRole('button', { name: 'Confirm import', exact: true })).toHaveCount(0)
    await page.getByLabel(`Answer column for ${sheet}`, { exact: true }).fill('C')
    await page.getByLabel(`Identifier column for ${sheet} (optional)`, { exact: true }).fill('A')
    await expect(page.getByLabel(`Include hidden rows and sheets for ${sheet}`, { exact: true })).not.toBeChecked()
    await expect(page.getByLabel(`Allow overwriting existing answers for ${sheet}`, { exact: true })).not.toBeChecked()
    const operations = page.getByLabel('Map Operations', { exact: true })
    await operations.focus(); await page.keyboard.press('Space'); await expect(operations).toBeChecked()
    await page.getByLabel('Header row for Operations', { exact: true }).fill('1')
    await page.getByLabel('Question column for Operations', { exact: true }).fill('A')
    await page.getByLabel('Answer column for Operations', { exact: true }).fill('B')
    await keyboardActivate(page, page.getByRole('button', { name: 'Preview mapped questions', exact: true }))
    await expect(page.getByText('5 questions total. Showing 5 rows.', { exact: true })).toBeVisible()
    await accessibility(page)
    await keyboardActivate(page, page.getByRole('button', { name: 'Confirm import', exact: true }))
    await expect(page.getByText('Workbook imported', { exact: true })).toBeVisible()
    await keyboardActivate(page, page.getByRole('button', { name: `Open ${kind}.xlsx`, exact: true }))
    await keyboardActivate(page, page.getByRole('button', { name: 'Review answers', exact: true }))
    await keyboardActivate(page, page.getByRole('button', { name: 'Draft remaining items', exact: true }))
    await expect(page.getByText('Drafting complete. All generated answers still require human review.', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reload review page', exact: true })).toBeEnabled()
    const first = page.getByRole('article').filter({ hasText: `${sheet} · Row ${header + 1} ·` })
    const second = page.getByRole('article').filter({ hasText: `${sheet} · Row ${header + 2} ·` })
    const operationItem = page.getByRole('article').filter({ hasText: 'Operations · Row 2 ·' })
    await expect(first.locator('blockquote').filter({ hasText: 'AES-256' })).toBeVisible()
    await expect(first.locator('figcaption').filter({ hasText: 'Synthetic journey policy · Version journey-v1' })).toBeVisible()
    const missing = page.getByRole('article').filter({ hasText: 'Is biometric authentication available?' })
    await expect(missing.getByText(/Missing evidence: this draft cannot be approved/)).toBeVisible()
    await expect(missing.getByRole('button', { name: 'Approve revision 1', exact: true })).toBeDisabled()
    await accessibility(page)

    await page.getByLabel('Reviewer label (unverified)', { exact: true }).fill('Journey reviewer')
    const answer = 'Reviewed: Customer data is encrypted at rest using AES-256.'
    await first.getByLabel('Answer text', { exact: true }).focus(); await first.getByLabel('Answer text', { exact: true }).fill(answer)
    await page.keyboard.press('Tab'); await expect(first.getByLabel('Owner label (optional)', { exact: true })).toBeFocused()
    await first.getByLabel('Owner label (optional)', { exact: true }).fill('Security SME')
    await page.keyboard.press('Tab'); await expect(first.getByRole('button', { name: 'Save new revision', exact: true })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(first.getByText('Revision 2 saved. A new explicit approval is required.', { exact: true })).toBeVisible()
    await keyboardActivate(page, first.getByRole('button', { name: 'Approve revision 2', exact: true }))
    await expect(first.getByText('Revision 2 approved.', { exact: true })).toBeVisible()
    for (const item of [second, operationItem]) {
      await keyboardActivate(page, item.getByRole('button', { name: 'Approve revision 1', exact: true }))
      await expect(item.getByText('Revision 1 approved.', { exact: true })).toBeVisible()
    }
    const selected = { [`${sheet}!C${header + 1}`]: answer, [`${sheet}!C${header + 2}`]: await second.getByLabel('Answer text', { exact: true }).inputValue(), 'Operations!B2': await operationItem.getByLabel('Answer text', { exact: true }).inputValue() }
    const downloadEvent = page.waitForEvent('download')
    await keyboardActivate(page, page.getByRole('button', { name: 'Download export bundle', exact: true }))
    const download = await downloadEvent
    expect(download.suggestedFilename()).toBe('questionnaire-export.zip')
    const path = testInfo.outputPath('journey.zip'); await download.saveAs(path); expect(await download.failure()).toBeNull()
    const verified = JSON.parse(execFileSync(process.env.EVIDENCEDESK_BROWSER_PYTHON!, ['-m', 'scripts.inspect_export_bundle', path, JSON.stringify({ kind, selected, unresolved: { [`${sheet}!C${header + 4}`]: 'existing_answer_preserved', [`${sheet}!C${header + 5}`]: 'current_revision_not_approved' } })], { cwd: resolve(import.meta.dirname, '../..'), encoding: 'utf8' }))
    expect(verified.selected_count).toBe(3); expect(verified.unresolved_count).toBe(2)
    await expect(page.getByText('3 answers applied · 2 unresolved · 5 total', { exact: true })).toBeVisible()
    await accessibility(page)
    expect(errors).toEqual([]); expect(external).toEqual([])
    expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 })
  })
}

test('journey invalid key: keyboard manual authentication failure and automatic recovery', async ({ page }) => {
  await page.goto('/'); await expect(page.getByText('Your workspace is connected')).toBeVisible()
  await keyboardActivate(page, page.getByRole('button', { name: 'Disconnect and clear key', exact: true }))
  await page.getByLabel('API key', { exact: true }).fill('invalid-synthetic-key')
  await keyboardActivate(page, page.getByRole('button', { name: 'Connect workspace', exact: false }))
  await expect(page.getByRole('alert')).toContainText('Invalid API key')
  await expect(page.getByRole('heading', { name: 'Your workspace is connected', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('')
  await accessibility(page)
  await keyboardActivate(page, page.getByRole('button', { name: 'Connect automatically', exact: true }))
  await expect(page.getByText('Your workspace is connected')).toBeVisible()
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 })
})
