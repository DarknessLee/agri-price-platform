/** 数据库校验门禁：表结构、数据量、引用完整性、关键业务数据。 */
import { DatabaseSync } from 'node:sqlite'
import path from 'node:path'
import { Checker, ROOT } from './lib.mjs'

const checker = new Checker('数据库校验')
const dbPath = path.join(ROOT, '.runtime', 'agri.db')

let db
try {
  db = new DatabaseSync(dbPath, { readOnly: true })
} catch (error) {
  checker.check(`数据库文件可读：${dbPath}`, false, String(error))
  process.exit(checker.finish() ? 0 : 1)
}

function scalar(sql, ...params) {
  const row = db.prepare(sql).get(...params)
  return row ? Object.values(row)[0] : null
}

function tableExists(name) {
  return Boolean(scalar("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", name))
}

const expectedTables = [
  'sys_role',
  'sys_permission',
  'sys_role_permission',
  'sys_menu',
  'sys_user',
  'dim_variety',
  'dim_region',
  'dim_market',
  'dim_data_source',
  'price_record',
  'feature_record',
  'model_version',
  'forecast_result',
  'forecast_batch',
  'forecast_batch_item',
  'backtest_record',
  'alert_rule',
  'alert_record',
  'scenario_sim',
  'report',
  'import_task',
  'quality_issue',
  'scheduled_task',
  'audit_log',
]

const missing = expectedTables.filter((name) => !tableExists(name))
checker.check('核心数据表齐全（24 张）', missing.length === 0, `缺少：${missing.join(', ')}`)

const counts = {
  varieties: scalar('SELECT COUNT(*) FROM dim_variety'),
  regions: scalar('SELECT COUNT(*) FROM dim_region'),
  markets: scalar('SELECT COUNT(*) FROM dim_market'),
  users: scalar('SELECT COUNT(*) FROM sys_user'),
  permissions: scalar('SELECT COUNT(*) FROM sys_permission'),
  rolePermissions: scalar('SELECT COUNT(*) FROM sys_role_permission'),
  menus: scalar('SELECT COUNT(*) FROM sys_menu'),
  prices: scalar('SELECT COUNT(*) FROM price_record'),
  features: scalar('SELECT COUNT(*) FROM feature_record'),
  alerts: scalar('SELECT COUNT(*) FROM alert_record'),
  rules: scalar('SELECT COUNT(*) FROM alert_rule'),
  reports: scalar('SELECT COUNT(*) FROM report'),
  models: scalar('SELECT COUNT(*) FROM model_version'),
  forecasts: scalar('SELECT COUNT(*) FROM forecast_result'),
  scenarios: scalar('SELECT COUNT(*) FROM scenario_sim'),
  qualityIssues: scalar('SELECT COUNT(*) FROM quality_issue'),
  importTasks: scalar('SELECT COUNT(*) FROM import_task'),
  tasks: scalar('SELECT COUNT(*) FROM scheduled_task'),
  audits: scalar('SELECT COUNT(*) FROM audit_log'),
  sources: scalar('SELECT COUNT(*) FROM dim_data_source'),
}

console.log('数据量统计：', JSON.stringify(counts))
checker.equal('品种数量 = 5', counts.varieties, 5)
checker.equal('地区数量 = 6', counts.regions, 6)
checker.equal('市场数量 = 12', counts.markets, 12)
checker.equal('用户数量 = 7', counts.users, 7)
checker.equal('权限点数量 = 21', counts.permissions, 21)
checker.check('角色权限关联 >= 40', counts.rolePermissions >= 40, `实际 ${counts.rolePermissions}`)
checker.check('菜单数量 >= 15', counts.menus >= 15, `实际 ${counts.menus}`)
checker.check('价格记录 >= 80000', counts.prices >= 80000, `实际 ${counts.prices}`)
checker.check('特征记录 >= 30000', counts.features >= 30000, `实际 ${counts.features}`)
checker.check('预警记录 >= 6', counts.alerts >= 6, `实际 ${counts.alerts}`)
checker.check('预警规则 >= 6', counts.rules >= 6, `实际 ${counts.rules}`)
checker.check('分析报告 >= 3', counts.reports >= 3, `实际 ${counts.reports}`)
checker.check('调度任务 = 5', counts.tasks === 5, `实际 ${counts.tasks}`)
checker.check('数据源 >= 4', counts.sources >= 4, `实际 ${counts.sources}`)
checker.check('质量异常 >= 20', counts.qualityIssues >= 20, `实际 ${counts.qualityIssues}`)
checker.check('导入任务 >= 3', counts.importTasks >= 3, `实际 ${counts.importTasks}`)
checker.check('审计日志 >= 18', counts.audits >= 18, `实际 ${counts.audits}`)
checker.check('模型版本 >= 4（已完成训练）', counts.models >= 4, `实际 ${counts.models}`)
checker.check('预测结果记录 >= 5', counts.forecasts >= 5, `实际 ${counts.forecasts}`)

// 时间范围
const minDate = scalar('SELECT MIN(price_date) FROM price_record')
const maxDate = scalar('SELECT MAX(price_date) FROM price_record')
checker.check('价格数据起始日期 <= 2023-01-01', String(minDate) <= '2023-01-01', `实际 ${minDate}`)
checker.check('价格数据最新日期 >= 2026-11-11', String(maxDate) >= '2026-11-11', `实际 ${maxDate}`)

// 唯一性：同品种/市场/日期/市场类型不允许重复
const dupPrice = scalar(
  `SELECT COUNT(*) FROM (
     SELECT variety_id, market_id, price_date, market_type, COUNT(*) AS c
     FROM price_record GROUP BY variety_id, market_id, price_date, market_type HAVING c > 1
   )`,
)
checker.equal('价格记录无重复点', dupPrice, 0)

// 引用完整性
const orphanPrices = scalar(
  `SELECT COUNT(*) FROM price_record p
   LEFT JOIN dim_variety v ON v.id = p.variety_id
   LEFT JOIN dim_region r ON r.id = p.region_id
   LEFT JOIN dim_market m ON m.id = p.market_id
   WHERE v.id IS NULL OR r.id IS NULL OR m.id IS NULL`,
)
checker.equal('价格记录品种/地区/市场引用完整', orphanPrices, 0)

const orphanFeatures = scalar(
  `SELECT COUNT(*) FROM feature_record f
   LEFT JOIN dim_variety v ON v.id = f.variety_id
   LEFT JOIN dim_region r ON r.id = f.region_id
   WHERE v.id IS NULL OR r.id IS NULL`,
)
checker.equal('特征记录引用完整', orphanFeatures, 0)

const orphanAlerts = scalar(
  `SELECT COUNT(*) FROM alert_record a
   LEFT JOIN alert_rule ru ON ru.id = a.rule_id
   WHERE ru.id IS NULL`,
)
checker.equal('预警记录均关联有效规则', orphanAlerts, 0)

const orphanForecast = scalar(
  `SELECT COUNT(*) FROM forecast_result f
   LEFT JOIN model_version m ON m.id = f.model_id
   WHERE m.id IS NULL`,
)
checker.equal('预测结果均关联模型版本', orphanForecast, 0)

// 业务合理性
const badPrice = scalar('SELECT COUNT(*) FROM price_record WHERE price <= 0 OR price IS NULL')
checker.equal('价格均大于 0', badPrice, 0)

const badQuality = scalar(
  "SELECT COUNT(*) FROM price_record WHERE quality_flag NOT IN ('正常', '缺失', '异常', '重复', '疑似异常', '缺失估算')",
)
checker.equal('质量标记取值合法', badQuality, 0)

const badStatus = scalar("SELECT COUNT(*) FROM alert_record WHERE status NOT IN ('待处理', '处理中', '已关闭')")
checker.equal('预警状态取值合法', badStatus, 0)

const activeModels = scalar("SELECT COUNT(*) FROM model_version WHERE is_active = 1")
checker.check('存在启用中的模型', activeModels >= 1, `实际 ${activeModels}`)

const adminUser = scalar("SELECT COUNT(*) FROM sys_user WHERE username = 'admin' AND status = '启用'")
checker.equal('管理员账号存在且启用', adminUser, 1)

const adminPerms = scalar(
  `SELECT COUNT(*) FROM sys_role_permission rp WHERE rp.role_key = 'admin'`,
)
checker.check('admin 角色拥有全部权限点（21）', adminPerms === 21 || adminPerms >= 21, `实际 ${adminPerms}`)

const viewerPerms = scalar(
  `SELECT COUNT(*) FROM sys_role_permission rp WHERE rp.role_key = 'viewer' AND rp.perm_key LIKE 'admin:%'`,
)
checker.equal('观察员不含后台管理权限', viewerPerms, 0)

db.close()
process.exit(checker.finish() ? 0 : 1)
