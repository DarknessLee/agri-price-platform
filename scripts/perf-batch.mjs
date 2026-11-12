/**
 * 批量预测性能压测：30 个品种×地区组合 × 14 天预测，测算创建→完成耗时与吞吐，
 * 并按线性外推 1 万条预测点的耗时（方案目标：≤ 10 分钟）。
 *
 * 用法（需先用 .venv python 启动后端到 8018 端口）：
 *   node scripts/perf-batch.mjs
 *   API_BASE_URL=http://127.0.0.1:8017 node scripts/perf-batch.mjs
 *
 * 判定：外推 1 万点耗时 ≤ 600 秒则退出码 0，否则退出码 1。
 */
const BASE_URL = process.env.API_BASE_URL || 'http://127.0.0.1:8018'
const HORIZON = Number(process.env.PERF_HORIZON || 14)
const TARGET_POINTS = Number(process.env.PERF_TARGET_POINTS || 10000)
const TARGET_SECONDS = Number(process.env.PERF_TARGET_SECONDS || 600)
const POLL_INTERVAL_MS = 500
const MAX_WAIT_MS = 20 * 60 * 1000

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function callApi(pathname, { method = 'GET', token, body } = {}) {
  const response = await fetch(`${BASE_URL}${pathname}`, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(120000),
  })
  const text = await response.text()
  let payload = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = { raw: text.slice(0, 500) }
  }
  return { status: response.status, payload, code: payload?.code == null ? undefined : String(payload.code) }
}

async function main() {
  console.log(`[perf-batch] 目标服务：${BASE_URL}`)
  const login = await callApi('/api/auth/login', {
    method: 'POST',
    body: { username: 'admin', password: 'Admin@2026' },
  })
  const token = login.payload?.data?.token
  if (login.code !== '0' || !token) {
    console.error(`[perf-batch] 登录失败：${JSON.stringify(login.payload).slice(0, 300)}`)
    console.log('RESULT=FAIL 原因=登录失败')
    process.exitCode = 1
    return
  }

  const created = await callApi('/api/forecast/batch', {
    method: 'POST',
    token,
    body: { horizon: HORIZON },
  })
  const batchId = created.payload?.data?.batch_id
  if (created.code !== '0' || !batchId) {
    console.error(`[perf-batch] 创建批次失败：${JSON.stringify(created.payload).slice(0, 300)}`)
    console.log('RESULT=FAIL 原因=创建批次失败')
    process.exitCode = 1
    return
  }

  const startedAt = Date.now()
  const total = Number(created.payload?.data?.total || 0)
  console.log(
    `[perf-batch] 批次=${batchId} 组合数=${total} horizon=${HORIZON} 初始状态=${created.payload?.data?.status}`,
  )

  let lastProgress = -1
  let detail = null
  const terminal = new Set(['已完成', '部分失败', '失败'])
  while (Date.now() - startedAt < MAX_WAIT_MS) {
    const result = await callApi(`/api/forecast/batch/${batchId}`, { token })
    if (result.code !== '0') {
      console.error(`[perf-batch] 查询批次失败：${JSON.stringify(result.payload).slice(0, 300)}`)
      await sleep(POLL_INTERVAL_MS)
      continue
    }
    detail = result.payload.data
    const progress = Number(detail.progress ?? 0)
    if (progress !== lastProgress) {
      console.log(
        `[perf-batch] 状态=${detail.status} 进度=${progress}% done=${detail.done}/${detail.total}`,
      )
      lastProgress = progress
    }
    if (terminal.has(detail.status)) break
    await sleep(POLL_INTERVAL_MS)
  }

  const elapsedSeconds = (Date.now() - startedAt) / 1000
  if (!detail || !terminal.has(detail.status)) {
    console.log(`[perf-batch] 超时未完成：已等待 ${elapsedSeconds.toFixed(1)}s`)
    console.log('RESULT=FAIL 原因=批次超时')
    process.exitCode = 1
    return
  }

  const donePoints = (detail.items?.length || 0) * HORIZON
  const throughput = donePoints > 0 ? donePoints / Math.max(elapsedSeconds, 0.001) : 0
  const projectedSeconds = throughput > 0 ? TARGET_POINTS / throughput : Number.POSITIVE_INFINITY
  const pass = donePoints > 0 && projectedSeconds <= TARGET_SECONDS

  console.log(
    `[perf-batch] 完成：状态=${detail.status} done=${detail.done}/${detail.total} ` +
      `成功组合=${detail.items?.length || 0} 预测点=${donePoints} 耗时=${elapsedSeconds.toFixed(2)}s`,
  )
  console.log(
    `[perf-batch] 吞吐=${throughput.toFixed(2)} 点/秒 ` +
      `外推1万点=${Number.isFinite(projectedSeconds) ? projectedSeconds.toFixed(1) : '∞'}s ` +
      `目标≤${TARGET_SECONDS}s`,
  )
  console.log(`RESULT=${pass ? 'PASS' : 'FAIL'} batch=${batchId} points=${donePoints} ` +
    `elapsed=${elapsedSeconds.toFixed(2)}s throughput=${throughput.toFixed(2)}points/s ` +
    `projected=${Number.isFinite(projectedSeconds) ? projectedSeconds.toFixed(1) : 'inf'}s`)
  process.exitCode = pass ? 0 : 1
}

main().catch((error) => {
  console.error(`[perf-batch] 执行异常：${error?.stack || error}`)
  console.log('RESULT=FAIL 原因=执行异常')
  process.exitCode = 1
})
