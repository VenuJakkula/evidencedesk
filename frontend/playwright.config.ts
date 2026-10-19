import { defineConfig } from '@playwright/test'
if (!process.env.EVIDENCEDESK_BROWSER_BASE_URL) throw new Error('Run python -m scripts.workbook_browser to use isolated test servers.')
export default defineConfig({
  testDir: './browser', testMatch: process.env.EVIDENCEDESK_BROWSER_WORKFLOW === '1' ? 'workflow.spec.ts' : process.env.EVIDENCEDESK_BROWSER_OIDC === '1' ? 'enterprise.spec.ts' : /(?<!enterprise)(?<!workflow)\.spec\.ts$/,  fullyParallel: false, workers: 1, retries: 0, timeout: 60000, globalTimeout: 180000, maxFailures: 1,
  reporter: 'list', outputDir: './test-results',
  use: { baseURL: process.env.EVIDENCEDESK_BROWSER_BASE_URL, channel: process.env.EVIDENCEDESK_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium'), headless: true, trace: 'off', screenshot: 'off', video: 'off' },
})
