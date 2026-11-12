/** 数据库校验门禁：通过 scripts/db_validate.py 直连数据库（默认 MySQL 8），
 *  渲染 34 项结构、数据量、引用完整性与权限矩阵检查。 */
import { existsSync } from 'node:fs'
import path from 'node:path'
import { Checker, ROOT, runCapture, requireVenv } from './lib.mjs'

const checker = new Checker('数据库校验')
const scriptPath = path.join(ROOT, 'scripts', 'db_validate.py')

if (!existsSync(scriptPath)) {
  checker.check(`校验脚本存在：${scriptPath}`, false, '缺少 scripts/db_validate.py')
  process.exit(checker.finish() ? 0 : 1)
}

const python = requireVenv()
const result = runCapture(python, [scriptPath], {
  cwd: ROOT,
  timeout: 180000,
  env: { PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
})

let payload = null
const stdout = (result.stdout || '').trim()
try {
  payload = JSON.parse(stdout)
} catch {
  payload = null
}

if (!payload || !Array.isArray(payload.checks)) {
  const detail = (result.stderr || stdout || '').trim().split(/\r?\n/).slice(-5).join(' | ')
  checker.check(
    '数据库校验脚本可执行',
    false,
    `exit=${result.status} ${detail.slice(0, 500)}`.trim(),
  )
  process.exit(checker.finish() ? 0 : 1)
}

if (payload.counts && Object.keys(payload.counts).length > 0) {
  console.log('数据量统计：', JSON.stringify(payload.counts))
}

for (const item of payload.checks) {
  checker.check(item.name, Boolean(item.ok), item.detail || '')
}

process.exit(checker.finish() ? 0 : 1)
