/**
 * 五道门禁串联执行：build → db:validate → test:api → test:e2e → check:docs。
 * 任一门前失败即停止，并在末尾输出汇总 RESULT 行。
 */
import { ROOT, ensureDirs, report, runCapture } from './lib.mjs'

ensureDirs()
const startedAt = Date.now()
const startedAll = Date.now()

const gates = [
  { key: 'build', name: '构建门禁', script: 'scripts/build.mjs', timeout: 30 * 60 * 1000 },
  { key: 'db:validate', name: '数据库门禁', script: 'scripts/db-validate.mjs', timeout: 10 * 60 * 1000 },
  { key: 'test:api', name: '接口门禁', script: 'scripts/check-api.mjs', timeout: 60 * 60 * 1000 },
  { key: 'test:e2e', name: '端到端门禁', script: 'scripts/test-e2e.mjs', timeout: 60 * 60 * 1000 },
  { key: 'check:docs', name: '文档门禁', script: 'scripts/check-docs.mjs', timeout: 10 * 60 * 1000 },
]

const results = []
let totalPassed = 0
let totalFailed = 0
let stopped = false

for (const gate of gates) {
  if (stopped) {
    results.push({ ...gate, status: '跳过', passed: 0, failed: 0, seconds: 0 })
    continue
  }
  console.log(`\n${'='.repeat(72)}\n>>> 门禁：${gate.name}（${gate.script}）\n${'='.repeat(72)}`)
  const gateStart = Date.now()
  const result = runCapture(process.execPath, [gate.script], { cwd: ROOT, timeout: gate.timeout })
  if (result.stdout) process.stdout.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)

  const match = `${result.stdout}\n${result.stderr}`.match(/RESULT=(PASS|FAIL) passed=(\d+) failed=(\d+) 用时=([\d.]+)s/g)
  const last = match ? match[match.length - 1] : ''
  const parsed = last.match(/RESULT=(PASS|FAIL) passed=(\d+) failed=(\d+)/)
  const status = parsed ? parsed[1] : result.status === 0 ? 'PASS' : 'FAIL'
  const passed = parsed ? Number(parsed[2]) : 0
  const failed = parsed ? Number(parsed[3]) : status === 'PASS' ? 0 : 1
  const seconds = Math.round((Date.now() - gateStart) / 1000)

  totalPassed += passed
  totalFailed += failed
  results.push({ ...gate, status, passed, failed, seconds })
  if (status !== 'PASS') stopped = true
}

console.log(`\n${'='.repeat(72)}\n门禁汇总\n${'='.repeat(72)}`)
for (const item of results) {
  const mark = item.status === 'PASS' ? 'PASS' : item.status === 'FAIL' ? 'FAIL' : '跳过'
  console.log(` ${mark.padEnd(4)} | ${item.name.padEnd(12)} | 通过 ${String(item.passed).padStart(3)} 失败 ${String(item.failed).padStart(2)} | ${item.seconds}s`)
}
console.log(`总耗时：${Math.round((Date.now() - startedAll) / 1000)}s`)

const allPass = results.every((item) => item.status === 'PASS')
process.exit(report(allPass ? totalPassed : totalPassed, allPass ? 0 : Math.max(1, totalFailed), startedAt) ? 0 : 1)
