import { expect, test, type Page } from './fixtures'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { seedReview, draftReview } from './helpers'

type Selected = Record<string, string>
async function downloadAndVerify(page: Page, outputPath: string, kind: string, selected: Selected, unresolved: Record<string, string>) {
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download export bundle', exact: true }).click()
  const download = await downloadEvent
  expect(download.suggestedFilename()).toBe('questionnaire-export.zip')
  await download.saveAs(outputPath)
  expect(await download.failure()).toBeNull()
  const verification = JSON.parse(execFileSync(process.env.EVIDENCEDESK_BROWSER_PYTHON!, ['-m', 'scripts.inspect_export_bundle', outputPath, JSON.stringify({ kind, selected, unresolved })], { cwd: resolve(import.meta.dirname, '../..'), encoding: 'utf8' }))
  expect(verification.unchanged_cells_verified).toBe(true)
  await expect(page.getByText(`${verification.selected_count} answers applied · ${verification.unresolved_count} unresolved · 5 total`, { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Export receipt', exact: true }).getByText(new RegExp(verification.export_id))).toBeVisible()
  return verification
}
for (const kind of ['security', 'rfp'] as const) {
  test(`export ${kind}: actual ZIP cells, preservation and approved current revisions`, async ({ page }, testInfo) => {
    await seedReview(page, `export-${kind}`, { kind }); await draftReview(page)
    const sheet = kind === 'security' ? 'Security' : 'RFP'
    const header = kind === 'security' ? 1 : 3
    const first = page.getByRole('article').filter({ hasText: `${sheet} · Row ${header + 1} ·` })
    const second = page.getByRole('article').filter({ hasText: `${sheet} · Row ${header + 2} ·` })
    const operations = page.getByRole('article').filter({ hasText: 'Operations · Row 2 ·' })
    const preserved = page.getByRole('article').filter({ hasText: 'What transport encryption is used?' })
    await page.getByLabel('Reviewer label (unverified)', { exact: true }).fill('Export reviewer')
    const text = '=Reviewed AES-256 encryption response'
    await first.getByLabel('Answer text', { exact: true }).fill(text)
    await expect(page.getByRole('button', { name: 'Download export bundle', exact: true })).toBeDisabled()
    await first.getByRole('button', { name: 'Save new revision', exact: true }).click()
    await expect(first.getByText('Revision 2 saved. A new explicit approval is required.', { exact: true })).toBeVisible()
    await first.getByRole('button', { name: 'Approve revision 2', exact: true }).click()
    await expect(first.getByText('Revision 2 approved.', { exact: true })).toBeVisible()
    for (const item of [second, operations, preserved]) {
      await item.getByRole('button', { name: 'Approve revision 1', exact: true }).click()
      await expect(item.getByText('Revision 1 approved.', { exact: true })).toBeVisible()
    }
    const secondText = await second.getByLabel('Answer text', { exact: true }).inputValue()
    const operationsText = await operations.getByLabel('Answer text', { exact: true }).inputValue()
    const firstCell = `${sheet}!C${header + 1}`
    const selected = { [firstCell]: text, [`${sheet}!C${header + 2}`]: secondText, 'Operations!B2': operationsText }
    const unresolved = { [`${sheet}!C${header + 4}`]: 'existing_answer_preserved', [`${sheet}!C${header + 5}`]: 'current_revision_not_approved' }
    await expect(page.getByText(/completed.xlsx/).first()).toBeVisible()
    const initial = await downloadAndVerify(page, testInfo.outputPath('initial.zip'), kind, selected, unresolved)
    const receipt = page.getByRole('region', { name: 'Export receipt', exact: true })
    await expect(receipt.getByRole('cell', { name: 'Existing answer preserved', exact: true })).toBeVisible()
    await expect(receipt.getByRole('cell', { name: 'Current revision not approved', exact: true })).toBeVisible()
    await expect(page.getByRole('article').filter({ hasText: 'Is biometric authentication available?' })).toBeVisible()
    if (kind === 'security') {
      const revised = '-Reapproved AES-256 encryption response'
      await first.getByLabel('Answer text', { exact: true }).fill(revised)
      await first.getByRole('button', { name: 'Save new revision', exact: true }).click()
      await expect(first.getByText('Revision 3 saved. A new explicit approval is required.', { exact: true })).toBeVisible()
      // The old receipt remains a truthful snapshot until another explicit download.
      await expect(page.getByText('3 answers applied · 2 unresolved · 5 total', { exact: true })).toBeVisible()
      const { [firstCell]: ignored, ...remaining } = selected
      const edited = await downloadAndVerify(page, testInfo.outputPath('edited-unapproved.zip'), kind, remaining, { ...unresolved, [firstCell]: 'current_revision_not_approved' })
      expect(edited.export_id).not.toBe(initial.export_id)
      await first.getByRole('button', { name: 'Approve revision 3', exact: true }).click()
      await expect(first.getByText('Revision 3 approved.', { exact: true })).toBeVisible()
      const reapproved = await downloadAndVerify(page, testInfo.outputPath('reapproved.zip'), kind, { ...selected, [firstCell]: revised }, unresolved)
      expect(reapproved.export_id).not.toBe(edited.export_id)
    }
    expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 })
  })
}

test('export failures create no success claim; receipt failures retry metadata without another export', async ({ page }, testInfo) => {
  const fixture = await seedReview(page, 'export-errors')
  let attempts = 0
  let downloads = 0
  page.on('download', () => downloads++)
  await page.route(`**/api/questionnaires/${fixture.id}/export`, async route => {
    attempts++
    if (attempts === 1) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'export_unavailable', message: 'Synthetic export failure' } }) })
    else await route.continue()
  })
  await page.getByRole('button', { name: 'Download export bundle', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('No browser download was started')
  expect(downloads).toBe(0); expect(attempts).toBe(1)
  let receiptAttempts = 0
  await page.route(`**/api/questionnaires/${fixture.id}/exports/**`, async route => {
    receiptAttempts++
    if (receiptAttempts === 1) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'receipt_unavailable', message: 'Synthetic receipt interruption' } }) })
    else await route.continue()
  })
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download export bundle', exact: true }).click()
  const bundle = await downloaded; await bundle.saveAs(testInfo.outputPath('unreviewed.zip'))
  await expect(page.getByRole('alert')).toContainText('Bundle received, but its receipt could not load')
  await expect(page.getByText(/answers applied/)).toHaveCount(0)
  await page.getByRole('button', { name: 'Reload export receipt', exact: true }).click()
  await expect(page.getByText('0 answers applied · 5 unresolved · 5 total', { exact: true })).toBeVisible()
  expect(attempts).toBe(2); expect(downloads).toBe(1); expect(receiptAttempts).toBe(2)
  JSON.parse(execFileSync(process.env.EVIDENCEDESK_BROWSER_PYTHON!, ['-m', 'scripts.inspect_export_bundle', testInfo.outputPath('unreviewed.zip'), JSON.stringify({ kind: 'security', selected: {}, unresolved: { 'Security!C5': 'existing_answer_preserved' } })], { cwd: resolve(import.meta.dirname, '../..'), encoding: 'utf8' }))
})
