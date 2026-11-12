/**
 * 端到端门禁：启动后端（托管已构建前端）→ 运行 Playwright 用例 → 停止后端。
 * 依赖：先执行 npm run build 生成 frontend/dist。
 */
import path from 'node:path'
import { existsSync } from 'node:fs'
import { ROOT, ensureDirs, report, run, startBackend } from './lib.mjs'

ensureDirs()
const startedAt = Date.now()

const distIndex = path.join(ROOT, 'frontend', 'dist', 'index.html')
if (!existsSync(distIndex)) {
  console.error('未找到 frontend/dist，请先执行 npm run build')
  console.log('RESULT=FAIL passed=0 failed=1 用时=0.0s')
  process.exit(1)
}

const playwrightBin = path.join(
  ROOT,
  'node_modules',
  '.bin',
  process.platform === 'win32' ? 'playwright.cmd' : 'playwright',
)

const backend = await startBackend({ port: 8017, logFile: path.join(ROOT, '.runtime', 'logs', 'backend-e2e.log') })
let result
try {
  result = run(playwrightBin, ['test', '--reporter=list'], {
    cwd: ROOT,
    stdio: 'pipe',
    env: { E2E_BASE_URL: 'http://127.0.0.1:8017' },
    timeout: 30 * 60 * 1000,
  })
} finally {
  backend.stop()
}

const output = `${result.stdout}\n${result.stderr}`
console.log(output)

const countOf = (pattern) => {
  const match = output.match(pattern)
  return match ? Number(match[1]) : 0
}
const passed = countOf(/(\d+) passed/)
const failed = countOf(/(\d+) failed/) + countOf(/(\d+) did not run/)
const skipped = countOf(/(\d+) skipped/)
const timedOut = countOf(/(\d+) timed out/)

if (passed === 0 && failed === 0) {
  console.log('未能解析 Playwright 结果，按失败处理')
  process.exit(report(0, Math.max(1, timedOut || 1), startedAt) ? 0 : 1)
}

if (skipped > 0) console.log(`跳过用例：${skipped} 个`)
if (timedOut > 0) console.log(`超时用例：${timedOut} 个`)

process.exit(report(passed, failed || (timedOut > 0 ? timedOut : result.status === 0 ? 0 : 1), startedAt) ? 0 : 1)
