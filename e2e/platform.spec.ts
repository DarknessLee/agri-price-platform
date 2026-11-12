import { expect, test } from '@playwright/test'
import {
  applySession,
  collectPageProblems,
  expectMainContent,
  expectNoErrorBanner,
  gotoRoute,
  loginApi,
  ROUTES,
} from './helpers'

test.describe('平台基础与权限', () => {
  test('登录页可访问并完成账号登录', async ({ page }) => {
    await gotoRoute(page, '/login')
    await expect(page.locator('body')).toContainText('农产品价格')
    const usernameInput = page.locator('input[autocomplete="username"]')
    await expect(usernameInput).toBeVisible()
    await usernameInput.fill('admin')
    await page.locator('input[type="password"]').fill('Admin@2026')
    await page.getByRole('button', { name: /登\s*录/ }).click()
    await page.waitForURL('**/dashboard', { timeout: 30_000 })
    await expect(page.locator('body')).toContainText('综合驾驶舱')
  })

  test('未登录访问业务页面跳转登录页', async ({ page }) => {
    await page.goto('/admin/users', { waitUntil: 'domcontentloaded' })
    await page.waitForURL('**/login**', { timeout: 20_000 })
    await expect(page.locator('input[autocomplete="username"]')).toBeVisible()
  })

  test('观察员访问后台管理被拦截到无权页面', async ({ page, request }) => {
    const auth = await loginApi(request, 'viewer')
    await applySession(page, auth)
    await page.goto('/admin/users', { waitUntil: 'domcontentloaded' })
    await page.waitForURL(/\/forbidden/, { timeout: 20_000 })
    await expect(page.locator('body')).toContainText('无权')
  })

  test('观察员菜单不含系统管理分组', async ({ page, request }) => {
    const auth = await loginApi(request, 'viewer')
    await applySession(page, auth)
    await gotoRoute(page, '/dashboard')
    const sidebar = page.locator('.ap-sidebar, aside, .el-aside').first()
    await expect(sidebar).not.toContainText('用户管理')
    await expect(sidebar).toContainText('价格监测')
  })

  test('全部业务页面渲染正常且无接口错误', async ({ page, request }) => {
    const auth = await loginApi(request, 'admin')
    await applySession(page, auth)
    const problems = collectPageProblems(page)
    for (const route of ROUTES) {
      await gotoRoute(page, route.path)
      await expectMainContent(page)
      await expectNoErrorBanner(page)
      const heading = page.locator('body')
      await expect(heading).not.toContainText('页面不存在')
    }
    expect(problems, `页面问题：\n${problems.join('\n')}`).toEqual([])
  })
})
