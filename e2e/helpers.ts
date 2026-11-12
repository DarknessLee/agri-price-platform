import { expect, type APIRequestContext, type Page } from '@playwright/test'

export interface LoginUser {
  token: string
  expires_in: number
  user: {
    id: number
    username: string
    display_name: string
    role_key: string
    role_name: string
    org: string
  }
  permissions: string[]
}

export const ACCOUNTS = {
  admin: { username: 'admin', password: 'Admin@2026' },
  analyst: { username: 'analyst01', password: 'Analyst@2026' },
  operator: { username: 'operator01', password: 'Operator@2026' },
  viewer: { username: 'viewer01', password: 'Viewer@2026' },
}

export async function loginApi(request: APIRequestContext, role: keyof typeof ACCOUNTS = 'admin'): Promise<LoginUser> {
  const account = ACCOUNTS[role]
  const response = await request.post('/api/auth/login', { data: account })
  expect(response.ok(), `登录接口应返回 200（${account.username}）`).toBeTruthy()
  const body = await response.json()
  expect(String(body.code), `登录失败：${JSON.stringify(body).slice(0, 200)}`).toBe('0')
  return body.data as LoginUser
}

/** 将登录态写入 localStorage，页面加载时即为已登录状态。 */
export async function applySession(page: Page, auth: LoginUser) {
  await page.addInitScript(
    ([token, user, perms]) => {
      localStorage.setItem('ap_token', token)
      localStorage.setItem('ap_user', user)
      localStorage.setItem('ap_perms', perms)
    },
    [auth.token, JSON.stringify(auth.user), JSON.stringify(auth.permissions)],
  )
}

/** 通用页面健康检查：无 5xx 接口、无脚本异常、无占位文案、主内容已渲染。 */
export function collectPageProblems(page: Page) {
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(`脚本异常：${error.message}`))
  page.on('response', (response) => {
    const url = response.url()
    if (/\/api\//.test(url) && response.status() >= 500) {
      problems.push(`接口 ${response.status()}：${url.replace(/^https?:\/\/[^/]+/, '')}`)
    }
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const text = message.text()
      if (!/favicon|ERR_INTERNET_DISCONNECTED|ResizeObserver/i.test(text)) problems.push(`控制台错误：${text.slice(0, 160)}`)
    }
  })
  return problems
}

export async function gotoRoute(page: Page, route: string) {
  await page.goto(route, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle')
  await expect(page.locator('body')).not.toContainText('页面建设中')
}

export async function expectMainContent(page: Page) {
  const content = page.locator('.el-card, .el-table, .kpi-card, canvas, .page-card')
  await expect(content.first()).toBeVisible({ timeout: 25_000 })
}

export async function expectNoErrorBanner(page: Page) {
  await expect(page.locator('.el-alert--error')).toHaveCount(0)
  await expect(page.locator('.el-message--error')).toHaveCount(0)
}

export const ROUTES = [
  { path: '/dashboard', title: '综合驾驶舱' },
  { path: '/monitor/prices', title: '价格监测' },
  { path: '/monitor/analysis', title: '监测分析' },
  { path: '/forecast/short', title: '短期预测' },
  { path: '/forecast/batch', title: '批量预测' },
  { path: '/forecast/models', title: '模型管理' },
  { path: '/forecast/drift', title: '模型监测' },
  { path: '/alert/list', title: '预警信息' },
  { path: '/alert/rules', title: '预警规则' },
  { path: '/scenario', title: '情景推演' },
  { path: '/report', title: '分析报告' },
  { path: '/data/sources', title: '数据源管理' },
  { path: '/data/quality', title: '数据质量' },
  { path: '/data/import', title: '数据导入' },
  { path: '/admin/users', title: '用户管理' },
  { path: '/admin/roles', title: '角色权限' },
  { path: '/admin/base', title: '基础数据' },
  { path: '/admin/audit', title: '操作审计' },
  { path: '/admin/tasks', title: '任务调度' },
  { path: '/open-api', title: '开放 API' },
  { path: '/screen', title: '数据大屏' },
]
