/**
 * 交付截图：启动后端（托管已构建前端）→ 逐页截图到 docs/screenshots/。
 * 依赖：先执行 npm run build 与 npm run seed。
 */
import path from 'node:path'
import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs'
import { chromium } from '@playwright/test'
import { ROOT, SCREENSHOT_DIR, callApi, ensureDirs, report, startBackend } from './lib.mjs'

ensureDirs()
const startedAt = Date.now()
if (!existsSync(SCREENSHOT_DIR)) mkdirSync(SCREENSHOT_DIR, { recursive: true })
for (const name of readdirSync(SCREENSHOT_DIR)) {
  if (/\.(png|jpg|jpeg)$/i.test(name)) rmSync(path.join(SCREENSHOT_DIR, name))
}

const distIndex = path.join(ROOT, 'frontend', 'dist', 'index.html')
if (!existsSync(distIndex)) {
  console.error('未找到 frontend/dist，请先执行 npm run build')
  console.log('RESULT=FAIL passed=0 failed=1 用时=0.0s')
  process.exit(1)
}

const PAGES = [
  { path: '/login', file: '00-登录页.png', anonymous: true },
  { path: '/dashboard', file: '01-综合驾驶舱.png' },
  { path: '/monitor/prices', file: '02-价格监测.png' },
  { path: '/monitor/analysis', file: '03-监测分析.png' },
  { path: '/forecast/short', file: '04-短期预测.png', prepare: { button: /开始预测/, wait: 6000 } },
  { path: '/forecast/batch', file: '05-批量预测.png', prepare: { select: ['生猪', '北京'], button: /开始批量预测/, wait: 12000 } },
  { path: '/forecast/models', file: '06-模型管理.png' },
  { path: '/forecast/drift', file: '06b-模型监测.png', prepare: { row: true, wait: 2500 } },
  { path: '/alert/list', file: '07-预警信息.png' },
  { path: '/alert/rules', file: '08-预警规则.png' },
  { path: '/scenario', file: '09-情景推演.png', prepare: { template: '气象灾害', button: /开始推演/, wait: 5000 } },
  { path: '/report', file: '10-分析报告.png' },
  { path: '/data/sources', file: '11-数据源管理.png' },
  { path: '/data/quality', file: '12-数据质量.png' },
  { path: '/data/import', file: '13-数据导入.png' },
  { path: '/admin/users', file: '14-用户管理.png' },
  { path: '/admin/roles', file: '15-角色权限.png' },
  { path: '/admin/base', file: '16-基础数据.png' },
  { path: '/admin/audit', file: '17-操作审计.png' },
  { path: '/admin/tasks', file: '18-任务调度.png' },
  { path: '/open-api', file: '19-开放API.png' },
  { path: '/screen', file: '21-数据大屏.png', prepare: { wait: 6000 } },
  { path: '/admin/monitor', file: '22-系统监控.png', prepare: { wait: 5000 } },
]

const backend = await startBackend({ port: 8017, logFile: path.join(ROOT, '.runtime', 'logs', 'backend-screenshots.log') })
let browser
let saved = 0
const failedPages = []

try {
  const adminAuth = (
    await callApi('/api/auth/login', { method: 'POST', body: { username: 'admin', password: 'Admin@2026' } })
  ).data
  const viewerAuth = (
    await callApi('/api/auth/login', { method: 'POST', body: { username: 'viewer01', password: 'Viewer@2026' } })
  ).data
  if (!adminAuth?.token) throw new Error('管理员登录失败，无法截图')

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1680, height: 1050 },
    deviceScaleFactor: 1,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  })
  const page = await context.newPage()
  page.on('dialog', (dialog) => dialog.dismiss().catch(() => undefined))

  const storage = (auth) => ({
    token: auth.token,
    user: JSON.stringify(auth.user),
    perms: JSON.stringify(auth.permissions || []),
  })

  const setSession = async (auth) => {
    const store = storage(auth)
    await page.addInitScript(
      ([token, user, perms]) => {
        localStorage.setItem('ap_token', token)
        localStorage.setItem('ap_user', user)
        localStorage.setItem('ap_perms', perms)
      },
      [store.token, store.user, store.perms],
    )
  }

  for (const item of PAGES) {
    try {
      if (item.anonymous) {
        await context.clearCookies()
        await page.addInitScript(() => {
          localStorage.clear()
        })
        await page.goto(`http://127.0.0.1:8017${item.path}`, { waitUntil: 'domcontentloaded' })
      } else {
        await setSession(adminAuth)
        await page.goto(`http://127.0.0.1:8017${item.path}`, { waitUntil: 'domcontentloaded' })
        await page.waitForLoadState('networkidle')
      }
      if (item.prepare) {
        if (item.prepare.template) {
          await page.getByText(item.prepare.template, { exact: false }).first().click({ timeout: 8000 }).catch(() => undefined)
          await page.waitForTimeout(500)
        }
        if (item.prepare.row) {
          await page
            .locator('.el-table__body tbody tr, .el-table tbody tr')
            .first()
            .click({ timeout: 10000 })
            .catch(() => undefined)
          await page.waitForTimeout(1800)
        }
        if (item.prepare.select) {
          for (const [index, label] of item.prepare.select.entries()) {
            await page.locator('.page-card .el-select').nth(index).click({ timeout: 8000 }).catch(() => undefined)
            await page.waitForTimeout(400)
            await page.getByRole('option', { name: label, exact: false }).first().click({ timeout: 8000 }).catch(() => undefined)
            await page.keyboard.press('Escape')
            await page.waitForTimeout(300)
          }
        }
        const button = page.getByRole('button', { name: item.prepare.button }).first()
        if (await button.count()) {
          await button.click({ timeout: 8000 }).catch(() => undefined)
          await page.waitForTimeout(item.prepare.wait ?? 4000)
          await page.waitForLoadState('networkidle')
        }
      }
      await page.waitForTimeout(1800)
      // 收尾：关闭可能残留的下拉/浮层并把鼠标移出内容区，避免截图出现悬停菜单
      await page.keyboard.press('Escape').catch(() => undefined)
      await page.mouse.move(4, 420)
      await page.waitForTimeout(400)
      const target = path.join(SCREENSHOT_DIR, item.file)
      await page.screenshot({ path: target, fullPage: true })
      if (statSync(target).size > 8000) {
        saved += 1
        console.log(`已保存截图：${item.file}`)
      } else {
        failedPages.push(`${item.file}（文件过小）`)
      }
    } catch (error) {
      failedPages.push(`${item.file}（${String(error).slice(0, 120)}）`)
    }
  }

  // 无权访问页（观察员身份）
  try {
    await context.clearCookies()
    await page.addInitScript(() => localStorage.clear())
    await setSession(viewerAuth)
    await page.goto('http://127.0.0.1:8017/admin/users', { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(1500)
    const forbiddenPath = path.join(SCREENSHOT_DIR, '20-权限隔离.png')
    await page.screenshot({ path: forbiddenPath, fullPage: true })
    if (statSync(forbiddenPath).size > 8000) saved += 1
  } catch (error) {
    failedPages.push(`权限隔离页（${String(error).slice(0, 120)}）`)
  }
} finally {
  if (browser) await browser.close().catch(() => undefined)
  backend.stop()
}

  const ok = saved >= 22 && failedPages.length === 0
if (failedPages.length > 0) console.log(`截图失败：${failedPages.join('；')}`)
console.log(`截图目录：${SCREENSHOT_DIR}`)
process.exit(report(saved, failedPages.length, startedAt) && ok ? 0 : 1)
