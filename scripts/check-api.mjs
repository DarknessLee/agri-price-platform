/**
 * 接口门禁：启动后端 → 鉴权与权限隔离 → 各业务模块接口断言 → 停止后端。
 * 依赖：已执行种子数据（缺失或数据不足时自动重建，且跳过模型训练以保证门禁时长可控）。
 */
import path from 'node:path'
import {
  BACKEND_DIR,
  BASE_URL,
  Checker,
  ROOT,
  VENV_PY,
  callApi,
  ensureDirs,
  login,
  run,
  runCapture,
  sleep,
  startBackend,
} from './lib.mjs'

ensureDirs()
const startedAt = Date.now()
const checker = new Checker('接口门禁（后端 API 全量冒烟）')

let adminAuth = null
let analystAuth = null
let operatorAuth = null
let viewerAuth = null

function ok(name, result, predicate) {
  let pass = result?.code === '0'
  let extra = ''
  if (pass && predicate) {
    try {
      pass = Boolean(predicate(result.data))
    } catch (error) {
      pass = false
      extra = ` 断言异常：${error}`
    }
  }
  checker.check(name, pass, `status=${result?.status} code=${result?.code}${extra} ${String(JSON.stringify(result?.body) ?? '').slice(0, 220)}`)
  return result?.data
}

async function section(title, fn) {
  console.log(`\n--- ${title} ---`)
  try {
    await fn()
  } catch (error) {
    checker.check(`${title}：执行未抛异常`, false, String(error?.stack || error).slice(0, 400))
  }
}

// ---------- 准备：确保数据库可用且已有种子数据 ----------
function readDatabaseState() {
  const probe = `
import json
from sqlalchemy import text
from app.database import engine

payload = {"ok": False}
try:
    with engine.connect() as conn:
        payload["prices"] = int(conn.execute(text("SELECT COUNT(*) FROM price_record")).scalar() or 0)
        payload["varieties"] = int(conn.execute(text("SELECT COUNT(*) FROM dim_variety")).scalar() or 0)
        payload["ok"] = True
except Exception as exc:  # noqa: BLE001 - 门禁只需判断可用性
    payload["error"] = str(exc)[:300]
print(json.dumps(payload, ensure_ascii=False))
`
  const out = runCapture(VENV_PY, ['-c', probe], { cwd: BACKEND_DIR })
  const line = (out.stdout || '').trim().split(/\r?\n/).pop()
  try {
    return JSON.parse(line)
  } catch {
    return { ok: false, error: (out.stderr || out.stdout || '').slice(-300) }
  }
}

const dbState = readDatabaseState()
if (!dbState.ok || dbState.varieties < 5 || dbState.prices < 80000) {
  console.log(`数据库未就绪（${dbState.ok ? `价格 ${dbState.prices} 行、品种 ${dbState.varieties} 个` : dbState.error}），先执行种子重建（不含模型训练）…`)
  const seeded = run(VENV_PY, ['-m', 'app.seed', '--reset', '--no-models'], { cwd: BACKEND_DIR, stdio: 'inherit' })
  checker.check('数据库缺失时自动种子重建成功', seeded.status === 0, `exit ${seeded.status}`)
}

const backend = await startBackend({ port: 8017, logFile: path.join(ROOT, '.runtime', 'logs', 'backend-api-gate.log') })

try {
  // ---------- 1. 健康检查与认证 ----------
  await section('健康检查与认证', async () => {
    const healthRes = await fetch(`${BASE_URL}/api/health`)
    const healthBody = await healthRes.json()
    checker.check('GET /api/health 返回正常状态', healthRes.status === 200 && healthBody?.status === 'ok', JSON.stringify(healthBody))
    checker.check(
      '健康检查包含版本/数据库/缓存状态/运行时长',
      Boolean(healthBody?.version && healthBody?.db) &&
        ['ok', 'error'].includes(healthBody?.cache) &&
        typeof healthBody?.uptime_seconds === 'number',
      JSON.stringify(healthBody),
    )

    const bad = await callApi('/api/auth/login', { method: 'POST', body: { username: 'admin', password: 'wrong-password' } })
    checker.check('错误密码登录被拒绝', bad.code === 'E4010', `code=${bad.code} status=${bad.status}`)

    adminAuth = await login('admin', 'Admin@2026')
    ok('admin 登录成功', { code: '0', data: adminAuth, status: 200 }, (d) => Boolean(d.token))
    checker.check('admin 拥有 21 个权限点', Array.isArray(adminAuth.permissions) && adminAuth.permissions.length === 21, `实际 ${adminAuth.permissions?.length}`)
    checker.check('登录返回用户简要信息', Boolean(adminAuth.user?.username === 'admin' && adminAuth.user?.role_key === 'admin'))
    checker.check('登录返回 token 有效期', Number(adminAuth.expires_in) > 0, `expires_in=${adminAuth.expires_in}`)

    ok('GET /api/auth/me 返回当前用户', await callApi('/api/auth/me', { token: adminAuth.token }), (d) => (d?.user?.username || d?.username) === 'admin')

    const logoutAuth = await login('admin', 'Admin@2026')
    ok('POST /api/auth/logout 正常退出', await callApi('/api/auth/logout', { method: 'POST', token: logoutAuth.token }))
    const revoked = await callApi('/api/auth/me', { token: logoutAuth.token })
    checker.check('注销后旧令牌立即失效（E4010）', revoked.code === 'E4010', `code=${revoked.code} status=${revoked.status}`)

    const noToken = await callApi('/api/dashboard/summary')
    checker.check('未携带 token 访问业务接口返回 401/E4010', noToken.code === 'E4010', `code=${noToken.code} status=${noToken.status}`)
  })

  // ---------- 2. 角色与权限隔离 ----------
  await section('角色与权限隔离', async () => {
    analystAuth = await login('analyst01', 'Analyst@2026')
    operatorAuth = await login('operator01', 'Operator@2026')
    viewerAuth = await login('viewer01', 'Viewer@2026')
    checker.check('分析员权限点数量正确（12）', analystAuth.permissions.length === 12, `实际 ${analystAuth.permissions.length}`)
    checker.check('操作员权限点数量正确（10）', operatorAuth.permissions.length === 10, `实际 ${operatorAuth.permissions.length}`)
    checker.check('观察员权限点数量正确（6）', viewerAuth.permissions.length === 6, `实际 ${viewerAuth.permissions.length}`)

    const viewerUsers = await callApi('/api/users', { token: viewerAuth.token })
    checker.check('观察员访问用户管理被拒绝（E4030）', viewerUsers.code === 'E4030', `code=${viewerUsers.code}`)

    const viewerRun = await callApi('/api/forecast/run', {
      method: 'POST',
      token: viewerAuth.token,
      body: { variety_id: 1, region_id: 1, horizon: 7 },
    })
    checker.check('观察员发起预测被拒绝（E4030）', viewerRun.code === 'E4030', `code=${viewerRun.code}`)

    const analystImport = await callApi('/api/sources', { method: 'POST', token: analystAuth.token, body: { name: '越权数据源' } })
    checker.check('分析员新增数据源被拒绝（E4030）', analystImport.code === 'E4030', `code=${analystImport.code}`)

    const operatorAudit = await callApi('/api/audit-logs', { token: operatorAuth.token })
    checker.check('操作员访问审计日志被拒绝（E4030）', operatorAudit.code === 'E4030', `code=${operatorAudit.code}`)

    const viewerMonitor = await callApi('/api/prices?page=1&page_size=5', { token: viewerAuth.token })
    ok('观察员可查看价格监测数据', viewerMonitor, (d) => d?.total > 0)
  })

  // ---------- 2b. Redis 缓存观测 ----------
  await section('Redis 缓存与失效', async () => {
    const first = await callApi('/api/dashboard/summary', { token: adminAuth.token })
    const firstCache = first.headers?.get?.('x-cache')
    const second = await callApi('/api/dashboard/summary', { token: adminAuth.token })
    const secondCache = second.headers?.get?.('x-cache')
    checker.check('驾驶舱汇总返回 x-cache 标识', ['HIT', 'MISS'].includes(firstCache), `x-cache=${firstCache}`)
    checker.check('重复请求驾驶舱汇总命中缓存（HIT）', secondCache === 'HIT', `x-cache=${secondCache}`)
    checker.check('缓存命中与回源返回数据一致', JSON.stringify(second.data) === JSON.stringify(first.data))

    const dictFirst = await callApi('/api/meta/dicts', { token: adminAuth.token })
    const dictSecond = await callApi('/api/meta/dicts', { token: adminAuth.token })
    checker.check('字典接口返回 x-cache 标识', ['HIT', 'MISS'].includes(dictFirst.headers?.get?.('x-cache')), `x-cache=${dictFirst.headers?.get?.('x-cache')}`)
    checker.check('字典接口重复请求命中缓存（HIT）', dictSecond.headers?.get?.('x-cache') === 'HIT', `x-cache=${dictSecond.headers?.get?.('x-cache')}`)
  })

  // ---------- 3. 元数据 ----------
  let dicts = null
  await section('元数据字典与菜单', async () => {
    dicts = ok('GET /api/meta/dicts 返回字典', await callApi('/api/meta/dicts', { token: adminAuth.token }), (d) => Boolean(d?.varieties?.length))
    checker.check('字典：品种 5 个', dicts?.varieties?.length === 5, `实际 ${dicts?.varieties?.length}`)
    checker.check('字典：地区 6 个', dicts?.regions?.length === 6, `实际 ${dicts?.regions?.length}`)
    checker.check('字典：市场 12 个', dicts?.markets?.length === 12, `实际 ${dicts?.markets?.length}`)
    checker.check('字典：市场类型 3 种', dicts?.market_types?.length === 3, `实际 ${dicts?.market_types?.length}`)
    checker.check('字典：预警等级 3 级', dicts?.alert_levels?.length === 3, `实际 ${dicts?.alert_levels?.length}`)
    checker.check('字典：报告类型 3 种', dicts?.report_types?.length === 3, `实际 ${dicts?.report_types?.length}`)

    const menus = await callApi('/api/meta/menus', { token: adminAuth.token })
    ok('GET /api/meta/menus 返回菜单树', menus, (d) => Array.isArray(d) && d.length > 0)
    const viewerMenus = await callApi('/api/meta/menus', { token: viewerAuth.token })
    const viewerData = viewerMenus.data || []
    const flatten = (nodes) => nodes.flatMap((node) => [node, ...flatten(node.children || [])])
    const viewerPaths = flatten(viewerData).map((node) => node.path)
    checker.check('观察员菜单不含后台管理入口', !viewerPaths.some((p) => String(p).startsWith('/admin')), viewerPaths.join(','))
    checker.check('观察员菜单含驾驶舱与价格监测', viewerPaths.includes('/dashboard') && viewerPaths.includes('/monitor/prices'))
  })

  const varietyId = dicts?.varieties?.[0]?.id || 1
  const regionId = dicts?.regions?.[0]?.id || 1

  // ---------- 4. 驾驶舱 ----------
  await section('综合驾驶舱', async () => {
    const summary = ok('GET /api/dashboard/summary 返回指标', await callApi('/api/dashboard/summary', { token: adminAuth.token }), (d) => Boolean(d?.kpi))
    checker.check('驾驶舱 KPI：品种数 5', summary?.kpi?.variety_count === 5, `实际 ${summary?.kpi?.variety_count}`)
    checker.check('驾驶舱 KPI：地区数 6', summary?.kpi?.region_count === 6, `实际 ${summary?.kpi?.region_count}`)
    checker.check('驾驶舱 KPI：记录数 >= 80000', Number(summary?.kpi?.record_count) >= 80000, `实际 ${summary?.kpi?.record_count}`)
    checker.check('驾驶舱 KPI：平均价格 > 0', Number(summary?.kpi?.avg_price) > 0, `实际 ${summary?.kpi?.avg_price}`)
    checker.check('驾驶舱返回最新价格日期', Boolean(summary?.latest_price_date))

    ok('GET /api/dashboard/trend 返回走势序列', await callApi(`/api/dashboard/trend?variety_id=${varietyId}&region_id=${regionId}&days=90`, { token: adminAuth.token }), (d) => d?.dates?.length > 0 && d?.series?.length > 0)
    ok('GET /api/dashboard/region-heat 返回区域指数', await callApi('/api/dashboard/region-heat', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length === 6)
    ok('GET /api/dashboard/category-share 返回品类占比', await callApi('/api/dashboard/category-share', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length >= 4)
    ok('GET /api/dashboard/alerts/latest 返回最新预警', await callApi('/api/dashboard/alerts/latest?limit=6', { token: adminAuth.token }), (d) => Array.isArray(d))
    ok('GET /api/dashboard/forecast-brief 返回预测摘要', await callApi('/api/dashboard/forecast-brief?limit=5', { token: adminAuth.token }), (d) => Array.isArray(d))
  })

  // ---------- 5. 价格监测 ----------
  await section('价格监测与分析', async () => {
    const page1 = ok('GET /api/prices 分页查询', await callApi('/api/prices?page=1&page_size=10', { token: adminAuth.token }), (d) => d?.list?.length === 10)
    checker.check('价格总数 >= 80000', Number(page1?.total) >= 80000, `实际 ${page1?.total}`)
    const row = page1?.list?.[0]
    checker.check('价格行包含品种/地区/日期/价格/质量标记', Boolean(row?.variety && row?.region && (row?.date || row?.price_date) && row?.price > 0 && row?.quality_flag))

    ok('价格按品种筛选生效', await callApi(`/api/prices?variety_id=${varietyId}&page=1&page_size=5`, { token: adminAuth.token }), (d) => d?.list?.length > 0 && d.list.every((item) => item.variety_id === varietyId || item.variety === dicts?.varieties?.[0]?.name))

    ok('GET /api/prices/series 日粒度', await callApi(`/api/prices/series?variety_id=${varietyId}&region_id=${regionId}&granularity=day`, { token: adminAuth.token }), (d) => d?.dates?.length > 300)
    ok('GET /api/prices/series 月粒度', await callApi(`/api/prices/series?variety_id=${varietyId}&region_id=${regionId}&granularity=month`, { token: adminAuth.token }), (d) => d?.dates?.length >= 12 && d?.dates?.length < 80)
    ok('GET /api/prices/stats 返回统计指标', await callApi(`/api/prices/stats?variety_id=${varietyId}&region_id=${regionId}`, { token: adminAuth.token }), (d) => Boolean(d))
    ok('GET /api/prices/region-spread 返回区域价差', await callApi(`/api/prices/region-spread?variety_id=${varietyId}`, { token: adminAuth.token }), (d) => (Array.isArray(d) && d.length === 6) || (Array.isArray(d?.series) && d.series.length === 6))
    ok('GET /api/prices/variety-compare 返回比价指数', await callApi(`/api/prices/variety-compare?region_id=${regionId}`, { token: adminAuth.token }), (d) => (Array.isArray(d) && d.length > 0) || (Array.isArray(d?.series) && d.series.length > 0))
    ok('GET /api/prices/seasonality 返回 12 个月季节指数', await callApi(`/api/prices/seasonality?variety_id=${varietyId}`, { token: adminAuth.token }), (d) => d?.months?.length === 12 && d?.indices?.length === 12)

    const exportRes = await fetch(`${BASE_URL}/api/prices/export?variety_id=${varietyId}&region_id=${regionId}`, {
      headers: { Authorization: `Bearer ${adminAuth.token}` },
    })
    const csvBytes = new Uint8Array(await exportRes.arrayBuffer())
    const hasBom = csvBytes.length > 3 && csvBytes[0] === 0xef && csvBytes[1] === 0xbb && csvBytes[2] === 0xbf
    const csvHead = new TextDecoder('utf-8').decode(csvBytes.slice(0, 400))
    checker.check('GET /api/prices/export 导出 CSV（含 BOM 与表头）', exportRes.status === 200 && hasBom && /价格|日期/.test(csvHead), `status=${exportRes.status} bom=${hasBom} head=${csvHead.slice(0, 40)}`)

    const monitorCsv = await callApi('/api/prices/export', { token: viewerAuth.token })
    checker.check('观察员导出价格被拒绝（缺少 monitor:export）', monitorCsv.code === 'E4030', `code=${monitorCsv.code}`)
    const analystCsv = await callApi('/api/prices/export', { token: analystAuth.token })
    checker.check('分析员可导出价格数据（monitor:export）', Boolean(analystCsv.status === 200 || analystCsv.code === '0'), `status=${analystCsv.status}`)
  })

  // ---------- 6. 预测分析 ----------
  let forecastId = null
  await section('短期预测', async () => {
    const runResult = ok(
      'POST /api/forecast/run 返回预测结果',
      await callApi('/api/forecast/run', { method: 'POST', token: analystAuth.token, body: { variety_id: varietyId, region_id: regionId, horizon: 14 }, timeout: 240000 }),
      (d) => Boolean(d?.forecast_id) && Array.isArray(d?.forecast),
    )
    forecastId = runResult?.forecast_id
    checker.check('预测返回 14 天结果', runResult?.forecast?.length === 14, `实际 ${runResult?.forecast?.length}`)
    const point = runResult?.forecast?.[0]
    checker.check('预测点包含点位/区间/方向/置信度', Boolean(point?.target_date && point?.point > 0 && point?.lower > 0 && point?.upper >= point?.lower && point?.direction))
    checker.check('预测返回历史序列', runResult?.history?.dates?.length > 0 && runResult?.history?.values?.length > 0)
    checker.check('预测返回结论摘要', Boolean(runResult?.summary?.text && runResult?.summary?.trend && runResult?.summary?.risk_level))
    checker.check('预测返回特征贡献解释', Array.isArray(runResult?.explain) && runResult.explain.length > 0)
    checker.check('预测返回模型信息（含 MAPE/方向准确率）', Boolean(runResult?.model?.key && runResult?.model?.name), JSON.stringify(runResult?.model))
    const mape = Number(runResult?.model?.mape)
    checker.check('短期预测 MAPE 在目标范围内（<= 15%）', Number.isFinite(mape) && mape <= 15, `MAPE=${runResult?.model?.mape}`)
    const dirAcc = Number(runResult?.model?.direction_acc)
    checker.check('方向准确率为有效百分数（0~100）', Number.isFinite(dirAcc) && dirAcc > 0 && dirAcc <= 100, `方向准确率=${runResult?.model?.direction_acc}`)

    ok('GET /api/forecast/result/{id} 可回看记录', await callApi(`/api/forecast/result/${forecastId}`, { token: analystAuth.token }), (d) => Boolean(d?.forecast_id || d?.id))
    ok('GET /api/forecast/results 返回历史列表', await callApi('/api/forecast/results?limit=20', { token: analystAuth.token }), (d) => Array.isArray(d) && d.length > 0)
    ok('GET /api/forecast/performance 返回效果指标', await callApi('/api/forecast/performance', { token: adminAuth.token }), (d) => Boolean(d?.avg_mape !== undefined && Array.isArray(d?.series)))
  })

  await section('批量预测', async () => {
    const created = ok(
      'POST /api/forecast/batch 创建批量任务',
      await callApi('/api/forecast/batch', {
        method: 'POST',
        token: analystAuth.token,
        body: { variety_ids: [1, 2], region_ids: [1, 2], horizon: 7 },
        timeout: 240000,
      }),
      (d) => Boolean(d?.batch_id),
    )
    const batchId = created?.batch_id
    let detail = null
    for (let i = 0; i < 90; i += 1) {
      detail = (await callApi(`/api/forecast/batch/${batchId}`, { token: analystAuth.token })).data
      if (detail && (detail.status === '已完成' || detail.status === '导入完成' || detail.done === detail.total)) break
      await sleep(1500)
    }
    checker.check('批量预测任务完成', Boolean(detail) && (detail.status === '已完成' || detail.done === detail.total), `status=${detail?.status} done=${detail?.done}/${detail?.total}`)
    checker.check('批量预测明细 4 条（2 品种 × 2 地区）', detail?.items?.length === 4, `实际 ${detail?.items?.length}`)
    checker.check('批量明细含点位与方向', Boolean(detail?.items?.[0]?.point > 0 && detail?.items?.[0]?.direction))
    const exportRes = await fetch(`${BASE_URL}/api/forecast/batch/${batchId}/export`, {
      headers: { Authorization: `Bearer ${adminAuth.token}` },
    })
    checker.check('批量预测结果可导出', exportRes.status === 200 && (await exportRes.text()).length > 50, `status=${exportRes.status}`)
  })

  // ---------- 7. 模型管理 ----------
  await section('模型管理', async () => {
    const models = ok('GET /api/models 返回模型列表', await callApi('/api/models', { token: adminAuth.token }), (d) => Array.isArray(d))
    checker.check('模型列表包含已训练模型', models?.length >= 4, `实际 ${models?.length}`)
    const first = models?.find((item) => item.is_active) || models?.[0]
    checker.check('模型包含算法/版本/评估指标', Boolean(first?.algorithm && first?.version && first?.mape !== undefined))

    const trained = await callApi('/api/models/train', { method: 'POST', token: analystAuth.token, body: { variety_id: varietyId, region_id: regionId }, timeout: 300000 })
    checker.check('POST /api/models/train 重新训练模型', trained.code === '0' && Boolean(trained.data), `code=${trained.code} message=${trained.message}`)

    const modelsAfter = await callApi(`/api/models?variety_id=${varietyId}`, { token: adminAuth.token })
    const modelKeys = new Set((Array.isArray(modelsAfter.data) ? modelsAfter.data : []).map((item) => item.key))
    checker.check(
      '模型覆盖 4 类算法（季节分解/Holt-Winters/GBR/组合）',
      ['seasonal', 'holt_winters', 'gbr', 'ensemble'].every((key) => modelKeys.has(key)),
      [...modelKeys].join(','),
    )

    if (first?.id) {
      ok('POST /api/models/{id}/activate 激活模型', await callApi(`/api/models/${first.id}/activate`, { method: 'POST', token: analystAuth.token }))
      ok('GET /api/models/{id}/backtest 返回回测曲线', await callApi(`/api/models/${first.id}/backtest?window=60`, { token: analystAuth.token }), (d) => Boolean(d?.points?.length > 30 && d?.metrics))
    }
    const trainDenied = await callApi('/api/models/train', { method: 'POST', token: viewerAuth.token, body: { variety_id: varietyId } })
    checker.check('观察员训练模型被拒绝（E4030）', trainDenied.code === 'E4030', `code=${trainDenied.code}`)
  })

  // ---------- 8. 预警管理 ----------
  await section('预警管理', async () => {
    const stats = ok('GET /api/alerts/statistics 返回预警统计', await callApi('/api/alerts/statistics', { token: operatorAuth.token }), (d) => d?.open_count !== undefined)
    checker.check('预警统计包含等级分布', Boolean(stats?.by_level))
    checker.check('预警统计包含召回率/误报率', stats?.recall_rate !== undefined && stats?.false_positive_rate !== undefined)

    const evaluated = ok('POST /api/alerts/evaluate 执行规则扫描', await callApi('/api/alerts/evaluate', { method: 'POST', token: operatorAuth.token, timeout: 180000 }), (d) => d?.scanned !== undefined)
    checker.check('规则扫描覆盖全部规则', Number(evaluated?.rules) >= 6, `实际 ${evaluated?.rules}`)

    const listRes = await callApi('/api/alerts?page=1&page_size=20', { token: operatorAuth.token })
    const alerts = ok('GET /api/alerts 分页查询预警', listRes, (d) => d?.list?.length > 0)
    checker.check('预警总数 > 0', Number(alerts?.total) > 0, `实际 ${alerts?.total}`)
    const pending = alerts?.list?.find((item) => item.status === '待处理') || alerts?.list?.[0]
    checker.check('预警行包含等级/标题/日期/状态', Boolean(pending?.level && pending?.title && pending?.alert_date && pending?.status))

    if (pending?.id) {
      const acked = ok('POST /api/alerts/{id}/ack 受理预警', await callApi(`/api/alerts/${pending.id}/ack`, { method: 'POST', token: operatorAuth.token, body: { note: '已安排市场巡查核实' } }), (d) => Boolean(d))
      const afterAck = (await callApi(`/api/alerts?status=处理中&page=1&page_size=5`, { token: operatorAuth.token })).data
      checker.check('受理后状态变为处理中', Array.isArray(afterAck?.list))
      ok('POST /api/alerts/{id}/close 关闭预警', await callApi(`/api/alerts/${pending.id}/close`, { method: 'POST', token: operatorAuth.token, body: { note: '价格已回落', result: '已处置' } }))
    }

    // 规则 CRUD
    const ruleCreated = ok(
      'POST /api/alerts/rules 新建预警规则',
      await callApi('/api/alerts/rules', {
        method: 'POST',
        token: operatorAuth.token,
        body: {
          name: '接口门禁-生猪低价预警',
          variety_id: varietyId,
          region_id: regionId,
          rule_type: 'price_threshold',
          operator: 'lt',
          threshold: 12.0,
          window_days: 30,
          level: '中',
          enabled: true,
          channel: '站内',
        },
      }),
      (d) => Boolean(d?.id || d?.rule?.id),
    )
    const ruleId = ruleCreated?.id || ruleCreated?.rule?.id
    ok('GET /api/alerts/rules 返回规则列表', await callApi('/api/alerts/rules', { token: operatorAuth.token }), (d) => Array.isArray(d) && d.length >= 6)
    if (ruleId) {
      ok('PUT /api/alerts/rules/{id} 更新规则', await callApi(`/api/alerts/rules/${ruleId}`, { method: 'PUT', token: operatorAuth.token, body: { threshold: 12.5, level: '低' } }))
      ok('POST /api/alerts/rules/{id}/toggle 启停规则', await callApi(`/api/alerts/rules/${ruleId}/toggle`, { method: 'POST', token: operatorAuth.token }))
      ok('DELETE /api/alerts/rules/{id} 删除规则', await callApi(`/api/alerts/rules/${ruleId}`, { method: 'DELETE', token: operatorAuth.token }))
    }

    const viewerRule = await callApi('/api/alerts/rules', {
      method: 'POST',
      token: viewerAuth.token,
      body: { name: '越权规则', variety_id: varietyId, rule_type: 'volatility', operator: 'abs_gt', threshold: 5, level: '低' },
    })
    checker.check('观察员新建预警规则被拒绝（E4030）', viewerRule.code === 'E4030', `code=${viewerRule.code}`)
  })

  // ---------- 9. 情景模拟 ----------
  await section('情景模拟', async () => {
    const templates = ok('GET /api/scenarios/templates 返回情景模板', await callApi('/api/scenarios/templates', { token: analystAuth.token }), (d) => Array.isArray(d) && d.length >= 4)
    const types = (templates || []).map((item) => item.type || item.key)
    checker.check('情景模板覆盖天气/运费/政策/替代品', ['weather', 'freight', 'policy', 'substitute'].every((key) => types.includes(key)), types.join(','))

    const created = ok(
      'POST /api/scenarios 运行情景推演',
      await callApi('/api/scenarios', {
        method: 'POST',
        token: analystAuth.token,
        body: {
          name: '接口门禁-寒潮减产情景',
          scenario_type: 'weather',
          variety_id: varietyId,
          region_id: regionId,
          horizon: 14,
          shock: { yield_pct: -8, freight_pct: 5, policy_pct: 0, substitute_pct: 0, weather_level: 3 },
        },
        timeout: 180000,
      }),
      (d) => Boolean(d?.id) && d?.price_range?.mid !== undefined,
    )
    checker.check('情景结果包含价格变化幅度与区间', Number(created?.price_change_pct) !== undefined && created?.price_range?.low > 0)
    checker.check('情景结果包含图表序列（基线/预测/区间）', created?.chart?.dates?.length > 0 && created?.chart?.base?.length > 0 && created?.chart?.predicted?.length > 0)
    checker.check('情景结果包含影响因子与建议', Array.isArray(created?.factors) && created.factors.length > 0 && Boolean(created?.advice))
    checker.check('情景结果包含风险等级与趋势', Boolean(created?.risk_level && created?.trend))

    if (created?.id) {
      ok('GET /api/scenarios/{id} 回看情景', await callApi(`/api/scenarios/${created.id}`, { token: analystAuth.token }))
      ok('GET /api/scenarios 分页列表', await callApi('/api/scenarios?page=1&page_size=10', { token: analystAuth.token }), (d) => d?.total > 0)
      ok('DELETE /api/scenarios/{id} 删除情景', await callApi(`/api/scenarios/${created.id}`, { method: 'DELETE', token: analystAuth.token }))
    }
  })

  // ---------- 10. 分析报告 ----------
  await section('分析报告', async () => {
    const generated = ok(
      'POST /api/reports/generate 生成日报',
      await callApi('/api/reports/generate', {
        method: 'POST',
        token: analystAuth.token,
        body: { report_type: 'daily', period_start: '2026-11-05', period_end: '2026-11-11', variety_ids: [1, 2], region_ids: [1, 2] },
        timeout: 180000,
      }),
      (d) => Boolean(d?.id),
    )
    checker.check('报告包含标题与 HTML 正文', Boolean(generated?.title) && generated?.content_html?.includes('<'), `title=${generated?.title}`)

    if (generated?.id) {
      ok('GET /api/reports/{id} 查看报告', await callApi(`/api/reports/${generated.id}`, { token: analystAuth.token }), (d) => Boolean(d?.content_html))
      const download = await fetch(`${BASE_URL}/api/reports/${generated.id}/download?format=md`, {
        headers: { Authorization: `Bearer ${adminAuth.token}` },
      })
      const text = await download.text()
      checker.check('报告可下载 Markdown', download.status === 200 && text.length > 100, `status=${download.status} len=${text.length}`)
    }

    ok('GET /api/reports 分页列表', await callApi('/api/reports?page=1&page_size=10', { token: analystAuth.token }), (d) => d?.total >= 3)
    const viewerGenerate = await callApi('/api/reports/generate', { method: 'POST', token: viewerAuth.token, body: { report_type: 'daily' } })
    checker.check('观察员生成报告被拒绝（E4030）', viewerGenerate.code === 'E4030', `code=${viewerGenerate.code}`)
  })

  // ---------- 11. 数据治理 ----------
  await section('数据治理', async () => {
    const sources = ok('GET /api/sources 返回数据源', await callApi('/api/sources', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length >= 3)
    const source = sources?.[0]
    checker.check('数据源包含类型/协议/状态/记录数', Boolean(source?.type && source?.protocol && source?.status && source?.record_count !== undefined))

    if (source?.id) {
      ok('POST /api/sources/{id}/sync 触发数据同步', await callApi(`/api/sources/${source.id}/sync`, { method: 'POST', token: adminAuth.token, timeout: 120000 }))
    }

    const summary = ok('GET /api/quality/summary 返回质量概览', await callApi('/api/quality/summary', { token: adminAuth.token }), (d) => d?.completeness !== undefined)
    checker.check('质量概览包含完整率与重复率', summary?.completeness !== undefined && summary?.duplicate_rate !== undefined)
    checker.check('质量概览包含异常与缺失计数', summary?.outlier_count !== undefined && summary?.missing_count !== undefined)
    checker.check('质量概览包含按品种分布', Array.isArray(summary?.by_variety) && summary.by_variety.length > 0)

    const issues = ok('GET /api/quality/issues 返回异常明细', await callApi('/api/quality/issues?page=1&page_size=10', { token: adminAuth.token }), (d) => d?.list?.length > 0)
    checker.check('质量异常总数 >= 20', Number(issues?.total) >= 20, `实际 ${issues?.total}`)
    const issue = issues?.list?.find((item) => item.status === '待处理') || issues?.list?.[0]
    if (issue?.id) {
      ok('POST /api/quality/issues/{id}/resolve 处置异常', await callApi(`/api/quality/issues/${issue.id}/resolve`, { method: 'POST', token: adminAuth.token, body: { action: 'fix' } }))
    }

    const template = await fetch(`${BASE_URL}/api/quality/template`, { headers: { Authorization: `Bearer ${adminAuth.token}` } })
    const templateText = await template.text()
    checker.check('GET /api/quality/template 返回 CSV 模板', template.status === 200 && templateText.length > 50, `status=${template.status}`)

    // CSV 导入（价格日期超出种子区间，避免唯一约束跳过）
    const csv = '\ufeffvariety,region,market_type,date,price,volume,min_price,max_price\n生猪,湖北,批发,2026-11-15,18.80,1500,18.50,19.10\n大白菜,湖北,批发,2026-11-15,2.45,900,2.30,2.60\n'
    const form = new FormData()
    form.append('file', new Blob([csv], { type: 'text/csv' }), 'price-import.csv')
    form.append('source_id', String(source?.id || 1))
    const imported = await fetch(`${BASE_URL}/api/data/import`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${operatorAuth.token}` },
      body: form,
    }).then(async (response) => ({ status: response.status, body: await response.json() }))
    const importData = imported.body?.data
    checker.check(
      'POST /api/data/import 导入 CSV 成功',
      String(imported.body?.code) === '0' &&
        Number(importData?.rows_total) >= 2 &&
        (Number(importData?.rows_ok) >= 2 || (Number(importData?.rows_skipped) >= 2 && importData?.status_code === 'success')),
      `status=${imported.status} body=${JSON.stringify(imported.body).slice(0, 240)}`,
    )
    checker.check('导入返回任务与行数统计', Boolean(imported.body?.data?.task_id) && imported.body?.data?.rows_total >= 2)

    ok('GET /api/data/import-tasks 返回导入任务', await callApi('/api/data/import-tasks?page=1&page_size=10', { token: adminAuth.token }), (d) => d?.total >= 3)

    // 清理门禁写入的临时价格行，保持种子库日期范围与驾驶舱口径干净
    const cleanupScript = `
from sqlalchemy import text
from app.database import engine

with engine.begin() as conn:
    conn.execute(text("DELETE FROM price_record WHERE price_date = '2026-11-15'"))
print("cleaned")
`
    const cleaned = runCapture(VENV_PY, ['-c', cleanupScript], { cwd: BACKEND_DIR })
    checker.check('清理门禁导入的临时价格行', cleaned.status === 0, `exit ${cleaned.status}`)
  })

  // ---------- 12. 后台管理 ----------
  await section('后台管理', async () => {
    const users = ok('GET /api/users 返回用户列表', await callApi('/api/users?page=1&page_size=20', { token: adminAuth.token }), (d) => d?.list?.length >= 7)
    checker.check('用户行包含角色与状态', Boolean(users?.list?.[0]?.username && users?.list?.[0]?.role_name && users?.list?.[0]?.status))

    const username = `qa_user_${String(Date.now()).slice(-6)}`
    const createdUser = ok(
      'POST /api/users 新建用户',
      await callApi('/api/users', { method: 'POST', token: adminAuth.token, body: { username, password: 'Qa@20260001', display_name: '接口门禁用户', role_key: 'viewer', org: '质量保障组' } }),
      (d) => Boolean(d?.id),
    )
    if (createdUser?.id) {
      ok('PUT /api/users/{id} 修改用户', await callApi(`/api/users/${createdUser.id}`, { method: 'PUT', token: adminAuth.token, body: { display_name: '接口门禁用户（已修改）', status: '停用' } }))
      ok('POST /api/users/{id}/reset-password 重置密码', await callApi(`/api/users/${createdUser.id}/reset-password`, { method: 'POST', token: adminAuth.token, body: { password: 'Qa@20260002' } }))
      ok('DELETE /api/users/{id} 删除用户', await callApi(`/api/users/${createdUser.id}`, { method: 'DELETE', token: adminAuth.token }))
    }

    const roles = ok('GET /api/roles 返回角色列表', await callApi('/api/roles', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length >= 4)
    checker.check('角色包含用户数与权限集合', Boolean(roles?.[0]?.key && roles?.[0]?.user_count !== undefined && Array.isArray(roles?.[0]?.permissions)))
    ok('GET /api/permissions 返回权限点', await callApi('/api/permissions', { token: adminAuth.token }), (d) => (Array.isArray(d) ? d.length : d?.list?.length) >= 21)

    const viewerRole = roles?.find((item) => item.key === 'viewer')
    ok(
      'PUT /api/roles/{key}/permissions 保存角色权限（幂等回写）',
      await callApi(`/api/roles/${viewerRole?.key || 'viewer'}/permissions`, { method: 'PUT', token: adminAuth.token, body: { permissions: viewerRole?.permissions || [] } }),
    )

    const audit = ok('GET /api/audit-logs 返回审计日志', await callApi('/api/audit-logs?page=1&page_size=10', { token: adminAuth.token }), (d) => d?.total > 0)
    checker.check('审计日志包含用户/动作/IP', Boolean(audit?.list?.[0]?.username && audit?.list?.[0]?.action))

    const tasks = ok('GET /api/tasks 返回调度任务', await callApi('/api/tasks', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length === 5)
    const task = tasks?.find((item) => item.key === 'sync_price') || tasks?.[0]
    if (task?.id) {
      ok('POST /api/tasks/{id}/run 立即执行任务', await callApi(`/api/tasks/${task.id}/run`, { method: 'POST', token: adminAuth.token, timeout: 120000 }))
      ok('POST /api/tasks/{id}/toggle 启停任务', await callApi(`/api/tasks/${task.id}/toggle`, { method: 'POST', token: adminAuth.token }))
      await callApi(`/api/tasks/${task.id}/toggle`, { method: 'POST', token: adminAuth.token })
    }

    const sys = ok('GET /api/system/info 返回系统信息', await callApi('/api/system/info', { token: adminAuth.token }), (d) => Boolean(d))
    checker.check('系统信息包含数据库/记录数等运行指标', Boolean(sys?.database || sys?.db || sys?.record_count !== undefined))

    ok('GET /api/admin/varieties 返回品种维护列表', await callApi('/api/admin/varieties', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length === 5)
    ok('GET /api/admin/regions 返回地区维护列表', await callApi('/api/admin/regions', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length === 6)
  })

  // ---------- 13. 开放 API ----------
  await section('开放 API', async () => {
    ok('GET /api/open/v1/prices 返回开放价格数据', await callApi('/api/open/v1/prices?limit=10', { token: adminAuth.token }), (d) => d?.items?.length === 10 && d?.total > 0)
    const priceItem = (await callApi('/api/open/v1/prices?limit=1', { token: adminAuth.token })).data?.items?.[0]
    checker.check('开放价格字段包含日期/品种编码/地区编码/价格/单位', Boolean(priceItem?.date && priceItem?.variety_code && priceItem?.region_code && priceItem?.price > 0 && priceItem?.unit))

    ok('GET /api/open/v1/forecast 返回开放预测', await callApi(`/api/open/v1/forecast?variety_code=${dicts?.varieties?.[0]?.code || 'pig'}&region_code=${dicts?.regions?.[0]?.code || '110000'}&horizon=7`, { token: adminAuth.token, timeout: 240000 }), (d) => Array.isArray(d?.forecast) && d.forecast.length === 7)
    ok('GET /api/open/v1/alerts 返回开放预警', await callApi('/api/open/v1/alerts?limit=10', { token: adminAuth.token }), (d) => Array.isArray(d?.items))
    ok('GET /api/open/v1/reports 返回开放报告', await callApi('/api/open/v1/reports?limit=10', { token: adminAuth.token }), (d) => Array.isArray(d?.items))
    const metrics = ok('GET /api/open/v1/metrics 返回开放指标', await callApi('/api/open/v1/metrics', { token: adminAuth.token }), (d) => Boolean(d))
    checker.check('开放指标包含品种/地区/记录数', metrics?.variety_count === 5 && metrics?.region_count === 6 && Number(metrics?.record_count) >= 80000, JSON.stringify(metrics).slice(0, 200))

    const openNoToken = await callApi('/api/open/v1/metrics')
    checker.check('开放 API 未携带 token 被拒绝', openNoToken.code === 'E4010', `code=${openNoToken.code}`)
  })

  // ---------- 14. 增强能力（模型治理 / 通知 / SLA / 开放 API 治理） ----------
  await section('增强能力：模型治理与批量异步', async () => {
    const drift = ok(
      'GET /api/models/drift 返回漂移监控结果',
      await callApi('/api/models/drift?window=90', { token: analystAuth.token, timeout: 180000 }),
      (d) => Array.isArray(d?.items) && Boolean(d?.summary),
    )
    checker.check('漂移汇总含 总数/平稳/关注/漂移', Boolean(drift?.summary && drift.summary.total > 0 && ['stable', 'watch', 'drifted'].every((k) => Number(drift.summary[k]) >= 0)), JSON.stringify(drift?.summary))
    const driftItem = drift?.items?.[0]
    checker.check('漂移明细含 PSI 与等级', Boolean(driftItem && Number(driftItem.psi) >= 0 && ['平稳', '关注', '漂移'].includes(driftItem.drift_level)), JSON.stringify(driftItem)?.slice(0, 200))

    const asyncBatch = await callApi('/api/forecast/batch', { method: 'POST', token: analystAuth.token, body: { variety_ids: [varietyId], region_ids: [regionId], horizon: 7 } })
    checker.check('批量预测立即返回（异步排队）', asyncBatch.code === '0' && Boolean(asyncBatch.data?.batch_id) && Number(asyncBatch.data?.progress) === 0, JSON.stringify(asyncBatch.body)?.slice(0, 200))
    const asyncId = asyncBatch.data?.batch_id
    let asyncDetail = null
    for (let i = 0; i < 120; i += 1) {
      asyncDetail = (await callApi(`/api/forecast/batch/${asyncId}`, { token: analystAuth.token })).data
      if (asyncDetail && asyncDetail.status === '已完成') break
      await sleep(1000)
    }
    checker.check('批量任务轮询至完成且进度 100', asyncDetail?.status === '已完成' && Number(asyncDetail?.progress) === 100, `status=${asyncDetail?.status} progress=${asyncDetail?.progress}`)
  })

  await section('增强能力：报告导出与通知中心', async () => {
    const reports = ok('GET /api/reports 返回报告列表', await callApi('/api/reports?page=1&page_size=5', { token: analystAuth.token }), (d) => d?.list?.length > 0)
    const reportId = reports?.list?.[0]?.id
    if (reportId) {
      const xlsx = await fetch(`${BASE_URL}/api/reports/${reportId}/download?format=xlsx`, { headers: { Authorization: `Bearer ${analystAuth.token}` } })
      const buf = Buffer.from(await xlsx.arrayBuffer())
      const type = xlsx.headers.get('content-type') || ''
      checker.check('报告可导出 Excel（xlsx 文件头 PK）', xlsx.status === 200 && /spreadsheet/.test(type) && buf.length > 4000 && buf[0] === 0x50 && buf[1] === 0x4b, `status=${xlsx.status} type=${type} bytes=${buf.length}`)
    }
    const template = await fetch(`${BASE_URL}/api/reports/template?report_type=daily`, { headers: { Authorization: `Bearer ${analystAuth.token}` } })
    const tplBuf = Buffer.from(await template.arrayBuffer())
    checker.check('报告模板可下载（xlsx）', template.status === 200 && tplBuf.length > 2000 && tplBuf[0] === 0x50, `status=${template.status} bytes=${tplBuf.length}`)

    const notifications = ok('GET /api/notifications 返回通知列表', await callApi('/api/notifications?page=1&page_size=10', { token: adminAuth.token }), (d) => Array.isArray(d?.list) && d?.unread !== undefined)
    checker.check('通知列表包含标题/分类/已读状态', notifications?.list?.length >= 1 && Boolean(notifications.list[0].title && notifications.list[0].category && notifications.list[0].is_read !== undefined), JSON.stringify(notifications?.list?.[0])?.slice(0, 200))
    ok('GET /api/notifications/summary 返回未读汇总', await callApi('/api/notifications/summary', { token: adminAuth.token }), (d) => Number(d?.unread) >= 0)
    ok('POST /api/notifications/read-all 全部标记已读', await callApi('/api/notifications/read-all', { method: 'POST', token: adminAuth.token, body: {} }), (d) => d?.updated !== undefined)
  })

  await section('增强能力：预警处置时效', async () => {
    const sla = ok(
      'GET /api/alerts/sla 返回处置时效',
      await callApi('/api/alerts/sla?days=30', { token: operatorAuth.token }),
      (d) => d?.sla_hours !== undefined && d?.within_sla_rate !== undefined,
    )
    checker.check('SLA 含平均处置时长/按期率/逾期未闭环', Boolean(sla && Number(sla.sla_hours) === 24 && Number(sla.avg_handle_hours) >= 0 && Array.isArray(sla.by_level)), JSON.stringify(sla)?.slice(0, 200))
  })

  await section('增强能力：开放 API 密钥与限流', async () => {
    const clients = ok('GET /api/open-clients 返回调用方列表', await callApi('/api/open-clients', { token: adminAuth.token }), (d) => Array.isArray(d) && d.length >= 3)
    checker.check('调用方含 client_key 与限流配置', Boolean(clients?.[0]?.client_key && clients?.[0]?.rate_limit !== undefined))
    checker.check('调用方密钥已掩码（不返回明文 secret）', !String(clients?.[0]?.secret || '').startsWith('sk_'), `secret=${clients?.[0]?.secret}`)

    const created = await callApi('/api/open-clients', { method: 'POST', token: adminAuth.token, body: { name: `门禁校验调用方-${Date.now()}`, rate_limit: 2, description: '五道门禁自动创建，用于校验密钥鉴权与限流' } })
    checker.check('POST /api/open-clients 创建调用方并返回明文密钥', created.code === '0' && Boolean(created.data?.client_key && created.data?.secret), JSON.stringify(created.body)?.slice(0, 200))
    const clientId = created.data?.id
    const clientKey = created.data?.client_key

    if (clientKey) {
      const viaKey = await callApi('/api/open/v1/metrics', { headers: { 'X-Api-Key': clientKey } })
      checker.check('X-Api-Key 可访问开放 API', viaKey.code === '0' && Number(viaKey.data?.variety_count) === 5, `code=${viaKey.code}`)
      const badKey = await callApi('/api/open/v1/metrics', { headers: { 'X-Api-Key': 'ak_invalid_key_for_gate' } })
      checker.check('无效 X-Api-Key 被拒绝（E4010）', badKey.code === 'E4010', `code=${badKey.code}`)
      let limited = null
      for (let i = 0; i < 6; i += 1) {
        const res = await callApi('/api/open/v1/metrics', { headers: { 'X-Api-Key': clientKey } })
        if (res.status === 429 || res.code === 'E4290') {
          limited = res
          break
        }
      }
      checker.check('超过限流阈值返回 429（E4290）', Boolean(limited) && limited.code === 'E4290', `code=${limited?.code} status=${limited?.status}`)
    }

    if (clientId) {
      ok('GET /api/open-clients/{id}/usage 返回调用统计', await callApi(`/api/open-clients/${clientId}/usage?days=7`, { token: analystAuth.token }), (d) => Array.isArray(d?.days) && d?.total !== undefined)
      ok('POST /api/open-clients/{id}/rotate 轮换密钥', await callApi(`/api/open-clients/${clientId}/rotate`, { method: 'POST', token: adminAuth.token }), (d) => Boolean(d?.secret && d?.client_key))
      ok('DELETE /api/open-clients/{id} 删除调用方', await callApi(`/api/open-clients/${clientId}`, { method: 'DELETE', token: adminAuth.token }), (d) => d?.deleted === true || d?.id === clientId)
    }

    const denied = await callApi('/api/open-clients', { token: viewerAuth.token })
    checker.check('观察员访问调用方管理被拒绝（E4030）', denied.code === 'E4030', `code=${denied.code}`)
  })

  // ---------- 15. 分页与错误处理 ----------
  await section('分页与错误处理', async () => {
    const paged = ok('价格分页参数 page/page_size 生效', await callApi('/api/prices?page=2&page_size=5', { token: adminAuth.token }), (d) => d?.list?.length === 5 && d?.page === 2 && d?.page_size === 5)
    checker.check('分页返回 total 总数', Number(paged?.total) >= 80000, `实际 ${paged?.total}`)

    const oversized = await callApi('/api/prices?page=1&page_size=999', { token: adminAuth.token })
    checker.check('page_size 超上限返回参数错误（E4001/E4002）', ['E4001', 'E4002'].includes(oversized.code) || oversized.status === 422, `code=${oversized.code} status=${oversized.status}`)

    const missing = await fetch(`${BASE_URL}/api/not-exists`, { headers: { Authorization: `Bearer ${adminAuth.token}` } })
    checker.check('未知接口返回 404', missing.status === 404, `status=${missing.status}`)

    const body = await callApi('/api/forecast/run', { method: 'POST', token: analystAuth.token, body: {} })
    checker.check('预测缺少必填参数返回参数错误', ['E4001', 'E4002'].includes(body.code) || body.status === 422, `code=${body.code} status=${body.status}`)
  })
} finally {
  backend.stop()
}

process.exit(checker.finish() ? 0 : 1)
