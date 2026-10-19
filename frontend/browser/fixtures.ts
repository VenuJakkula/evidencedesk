import { test as base, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'

// One worker; each case starts with an empty database owned by the temporary server harness.
export const test = base.extend<{ syntheticDatabase: void }>({
  syntheticDatabase: [async ({}, use) => {
    const python = process.env.EVIDENCEDESK_BROWSER_PYTHON
    const directory = process.env.EVIDENCEDESK_BROWSER_FIXTURE_DIR
    if (!python || !directory) throw new Error('Run python -m scripts.workbook_browser for isolated fixtures.')
    execFileSync(python, ['-m', 'scripts.browser_fixture', directory], { cwd: resolve(import.meta.dirname, '../..'), stdio: 'pipe' })
    await use()
  }, { auto: true }],
})
export { expect }
export type { Page } from '@playwright/test'
