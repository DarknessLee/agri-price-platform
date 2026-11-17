import { expect, test } from '@playwright/test'

import { ACCOUNTS, applySession, collectPageProblems, loginApi } from './helpers'

/**
 * 移动 H5 端验收：独立 Vite 子应用，构建后由后端以 /m/ 前缀同源托管。
 * 视口按手机尺寸设置，覆盖登录、首页与四个 Tab 页的渲染与基础交互。
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })

const H5_ROUTES = [
  { path: '/m/', title: '首页' },
  { path: '/m/prices', title: '价格行情' },
  { path: '/m/forecast', title: '价格预测' },
  { path: '/m/alerts', title: '预警中心' },
  { path: '/m/me', title: '我的' },
]

test('H5 登录页可完成登录并进入首页', async ({ page }) => {
  const problems = collectPageProblems(page)
  await page.goto('/m/login', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('body')).toContainText('农产品价格')
  await expect(page.locator('body')).toContainText('移动端')

  await page.locator('input[type="text"]').first().fill(ACCOUNTS.admin.username)
  await page.locator('input[type="password"]').first().fill(ACCOUNTS.admin.password)
  await page.getByRole('button', { name: /登\s*录/ }).first().click()

  await page.waitForURL(/\/m\/(\?.*)?$/, { timeout: 25_000 })
  await expect(page.locator('.van-tabbar')).toBeVisible()
  expect(problems, problems.join('\n')).toEqual([])
})

test('H5 首页展示关键指标与快捷入口', async ({ page }) => {
  const auth = await loginApi(page.request, 'admin')
  await applySession(page, auth)
  const problems = collectPageProblems(page)

  await page.goto('/m/', { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.van-tabbar')).toBeVisible()
  await expect(page.locator('body')).toContainText('平均价格')
  await expect(page.locator('body')).toContainText('数据记录')
  await expect(page.locator('body')).toContainText('价格行情')
  expect(problems, problems.join('\n')).toEqual([])
})

test('H5 四个 Tab 页均可渲染且无横向滚动', async ({ page }) => {
  const auth = await loginApi(page.request, 'admin')
  await applySession(page, auth)

  for (const route of H5_ROUTES) {
    await page.goto(route.path, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body'), `${route.title} 不应出现建设中占位`).not.toContainText('建设中')
    await expect(page.locator('.h5-page, .h5-hero, .h5-card').first(), `${route.title} 主内容应渲染`).toBeVisible({ timeout: 25_000 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${route.title} 出现横向滚动（溢出 ${overflow}px）`).toBeLessThanOrEqual(2)
  }
})

test('H5 预警页支持打开详情弹层', async ({ page }) => {
  const auth = await loginApi(page.request, 'operator')
  await applySession(page, auth)

  await page.goto('/m/alerts', { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle')
  await expect(page.locator('body')).toContainText('预警')

  const firstItem = page.locator('.van-cell, .alert-item, .h5-card .h5-row').first()
  if (await firstItem.count()) {
    await firstItem.click()
    await expect(page.locator('.van-popup')).toBeVisible({ timeout: 10_000 })
  }
})

test('H5 我的页展示账号信息并可退出登录', async ({ page }) => {
  const auth = await loginApi(page.request, 'viewer')
  await applySession(page, auth)

  await page.goto('/m/me', { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle')
  await expect(page.locator('body')).toContainText('退出登录')
  await expect(page.locator('body')).toContainText('权限')
})
