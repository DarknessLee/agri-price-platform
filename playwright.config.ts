import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8017'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: [['list'], ['json', { outputFile: '.runtime/artifacts/e2e-report.json' }], ['html', { outputFolder: '.runtime/artifacts/e2e-html', open: 'never' }]],
  use: {
    baseURL,
    headless: true,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1600, height: 1000 },
    screenshot: 'only-on-failure',
    video: 'off',
    trace: 'retain-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } },
    },
  ],
  outputDir: '.runtime/artifacts/e2e-results',
})
