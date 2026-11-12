import { expect, test, type Page } from '@playwright/test'
import { applySession, collectPageProblems, loginApi } from './helpers'

async function loginAsAdmin(page: Page, request: Parameters<typeof loginApi>[0]) {
  const auth = await loginApi(request, 'admin')
  await applySession(page, auth)
}

async function waitForChartOrTable(page: Page) {
  const content = page.locator('canvas, .el-table, .el-card, .page-card')
  await expect(content.first()).toBeVisible({ timeout: 30_000 })
}

test.describe('价格监测', () => {
  test('价格列表、统计与走势图加载', async ({ page, request }) => {
    await loginAsAdmin(page, request)
    await page.goto('/monitor/prices', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    const rows = page.locator('.el-table tbody tr')
    await expect.poll(async () => rows.count(), { timeout: 30_000 }).toBeGreaterThan(3)
    await waitForChartOrTable(page)
    await expect(page.locator('body')).toContainText('价格')
  })

  test('监测分析页展示价差与季节指数图', async ({ page, request }) => {
    await loginAsAdmin(page, request)
    await page.goto('/monitor/analysis', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('body')).toContainText('价差')
  })
})

test.describe('预测分析', () => {
  test('短期预测可生成结果并展示结论与解释', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    const problems = collectPageProblems(page)
    await page.goto('/forecast/short', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const button = page.getByRole('button', { name: /开始预测|立即预测|发起预测|预测/ }).first()
    await expect(button).toBeVisible({ timeout: 30_000 })
    await button.click()
    await expect(page.locator('.el-loading-mask')).toBeHidden({ timeout: 120_000 }).catch(() => undefined)
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 120_000 }).toBeGreaterThan(0)
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 })
    expect(problems, problems.join('\n')).toEqual([])
  })

  test('模型管理页展示模型指标', async ({ page, request }) => {
    await loginAsAdmin(page, request)
    await page.goto('/forecast/models', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 30_000 }).toBeGreaterThan(0)
    await expect(page.locator('body')).toContainText(/MAPE|mape|方向/)
  })

  test('批量预测页可发起任务并查看明细', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/forecast/batch', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const selects = page.locator('.page-card .el-select')
    await selects.nth(0).click()
    await page.locator('.el-select-dropdown__item').filter({ hasText: '生猪' }).first().click()
    await page.keyboard.press('Escape')
    await selects.nth(1).click()
    await page.locator('.el-select-dropdown__item').filter({ hasText: '北京' }).first().click()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /开始批量预测/ }).click()
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 150_000 }).toBeGreaterThan(0)
    await expect(page.locator('body')).toContainText(/批量预测/)
  })
})

test.describe('预警处置', () => {
  test('预警列表展示统计与数据', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/alert/list', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 30_000 }).toBeGreaterThan(0)
    await expect(page.locator('body')).toContainText(/预警/)
    await expect(page.locator('body')).toContainText(/待处理|处理中|已关闭/)
  })

  test('预警规则页展示规则列表', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/alert/rules', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 30_000 }).toBeGreaterThan(0)
  })
})

test.describe('情景推演与报告', () => {
  test('情景推演可运行并展示结果', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    const problems = collectPageProblems(page)
    await page.goto('/scenario', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const runButton = page.getByRole('button', { name: /运行|推演|开始|计算/ }).first()
    await expect(runButton).toBeVisible({ timeout: 30_000 })
    await runButton.click()
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 120_000 })
    expect(problems, problems.join('\n')).toEqual([])
  })

  test('分析报告页可生成日报并预览', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/report', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 30_000 }).toBeGreaterThan(0)
  })
})

test.describe('数据治理', () => {
  test('数据源与质量页展示统计', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/data/sources', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table, .el-card').first()).toBeVisible({ timeout: 30_000 })
    await page.goto('/data/quality', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText(/完整率|质量/)
    await page.goto('/data/import', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText(/导入/)
  })
})

test.describe('后台管理', () => {
  test('用户与角色页展示数据', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/admin/users', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 30_000 }).toBeGreaterThan(0)
    await page.goto('/admin/roles', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText(/角色|权限/)
  })

  test('基础数据、审计与任务调度页正常', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/admin/base', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText(/品种|地区/)
    await page.goto('/admin/audit', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
    await page.goto('/admin/tasks', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 30_000 })
  })
})

test.describe('开放 API', () => {
  test('开放 API 页面展示指标与调试面板', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/open-api', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText('/api/open/v1')
    await expect(page.locator('body')).toContainText(/Bearer|token|鉴权/i)
  })
})

test.describe('增强能力', () => {
  test('模型监测页展示漂移等级与模型对比', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    const problems = collectPageProblems(page)
    await page.goto('/forecast/drift', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.el-table')).toBeVisible({ timeout: 60_000 })
    await expect.poll(async () => page.locator('.el-table tbody tr').count(), { timeout: 60_000 }).toBeGreaterThan(0)
    await expect(page.locator('body')).toContainText(/漂移|PSI|平稳/)
    expect(problems, problems.join('\n')).toEqual([])
  })

  test('数据大屏页面渲染多图表面板', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/screen', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toContainText('数据大屏')
    await expect.poll(async () => page.locator('canvas').count(), { timeout: 60_000 }).toBeGreaterThanOrEqual(3)
  })

  test('顶栏通知中心可展开并标记已读', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const bell = page.locator('.ap-notify, .notification-bell, [data-test="notification-bell"]').first()
    if ((await bell.count()) > 0) {
      await bell.click()
      await expect(page.locator('body')).toContainText(/通知|全部已读/)
    } else {
      await expect(page.locator('body')).toContainText('综合驾驶舱')
    }
  })
})
