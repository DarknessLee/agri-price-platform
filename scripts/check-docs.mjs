/**
 * 文档门禁：交付文档完整性、内容要点、截图证据、界面占位残留、对外措辞。
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { Checker, ROOT, SCREENSHOT_DIR } from './lib.mjs'

const checker = new Checker('文档门禁')

function read(file) {
  const full = path.join(ROOT, file)
  return existsSync(full) ? readFileSync(full, 'utf8') : ''
}

function exists(file) {
  return existsSync(path.join(ROOT, file))
}

// ---------- 1. 交付文档齐全 ----------
const requiredDocs = [
  'README.md',
  'STATUS.md',
  'DECISIONS.md',
  'PLAN-MATRIX.md',
  'docs/方案解读卡.md',
  'docs/接口契约.md',
  'docs/用户手册.md',
  'docs/数据字典.md',
]
for (const file of requiredDocs) {
  checker.check(`交付文档存在：${file}`, exists(file))
}

// ---------- 2. README 关键信息 ----------
const readme = read('README.md')
checker.check('README 含项目简介与定位', /农产品价格/.test(readme) && readme.length > 800, `长度 ${readme.length}`)
checker.check('README 含环境要求（Python/Node 版本）', /Python 3\.1[0-9]/.test(readme) && /Node/.test(readme))
checker.check('README 含一键启动命令', /npm run (dev|gate|seed)/.test(readme))
checker.check('README 含种子数据重建命令', /npm run seed/.test(readme))
checker.check('README 含五道门禁说明', /门禁/.test(readme) && /RESULT=/.test(readme))
checker.check('README 含访问地址（前端 5177 / 后端 8017）', /5177/.test(readme) && /8017/.test(readme))
checker.check('README 含演示账号与角色说明', /admin/.test(readme) && /(analyst|分析师)/.test(readme))

// ---------- 3. STATUS / DECISIONS / PLAN-MATRIX ----------
const status = read('STATUS.md')
checker.check('STATUS 含当前阶段', /阶段/.test(status) && /M[0-9]/.test(status))
checker.check('STATUS 含最近更新时间', /2026-11-1[0-9]/.test(status))
checker.check('STATUS 含门禁结果记录', /RESULT=/.test(status))
checker.check('STATUS 含下一步列表', /下一步|Next/i.test(status))

const decisions = read('DECISIONS.md')
const missingDecisions = Array.from({ length: 11 }, (_, i) => `D${String(i + 1).padStart(2, '0')}`).filter(
  (key) => !decisions.includes(key),
)
checker.check('DECISIONS 覆盖 D01–D11 且无缺号', missingDecisions.length === 0, `缺少 ${missingDecisions.join(',')}`)

const matrix = read('PLAN-MATRIX.md')
const matrixRows = matrix.split('\n').filter((line) => line.startsWith('|') && !line.startsWith('| 方案') && !/^\|\s*-+/.test(line) && !line.startsWith('| 序号'))
checker.check('PLAN-MATRIX 覆盖方案条目（>= 25 行）', matrixRows.length >= 25, `实际 ${matrixRows.length}`)
checker.check('PLAN-MATRIX 含四类状态标注', ['已实现', '部分', '暂缓', '不做'].every((tag) => matrix.includes(tag)))
const implemented = matrixRows.filter((line) => line.includes('已实现'))
const evidenceMissing = implemented.filter((line) => /\|\s*—\s*\|/.test(line.split('|').slice(3, 8).join('|')) && !/`|\.py|\.vue|\.mjs|\.md/.test(line))
checker.check('PLAN-MATRIX 已实现条目均附证据（文件/接口/截图）', evidenceMissing.length === 0, `${evidenceMissing.length} 行缺少证据`)

// ---------- 4. 接口契约与实现清单 ----------
const contract = read('docs/接口契约.md')
const contractPaths = [
  '/api/auth/login',
  '/api/auth/me',
  '/api/meta/dicts',
  '/api/meta/menus',
  '/api/dashboard/summary',
  '/api/dashboard/trend',
  '/api/prices',
  '/api/prices/series',
  '/api/prices/seasonality',
  '/api/forecast/run',
  '/api/forecast/batch',
  '/api/forecast/performance',
  '/api/models',
  '/api/models/train',
  '/api/alerts',
  '/api/alerts/statistics',
  '/api/alerts/rules',
  '/api/scenarios',
  '/api/reports',
  '/api/sources',
  '/api/quality/summary',
  '/api/data/import',
  '/api/users',
  '/api/roles',
  '/api/audit-logs',
  '/api/tasks',
  '/api/open/v1/prices',
  '/api/open/v1/metrics',
]
const missingPaths = contractPaths.filter((item) => !contract.includes(item))
checker.check('接口契约覆盖全部核心端点（28 个）', missingPaths.length === 0, `缺少 ${missingPaths.join(',')}`)
checker.check('接口契约定义统一响应与错误码', /code.*message.*data/.test(contract) && /E4[0-9]{3}/.test(contract))
checker.check('接口契约定义 21 个权限点', (contract.match(/[a-z]+:(view|export|run|manage|handle|rule|generate|import|source|user|role|base|audit|task)/g) || []).length >= 21)

// ---------- 5. 长期文档与用户手册 ----------
// 阶段验收报告属于过程文档，交付后不再保留、也不纳入 git（见开发手册 01-工作流 §8）；
// 长期留存的是 STATUS / DECISIONS / 接口契约 / 数据字典 / 用户手册等。
checker.check('决策记录含编号决策项（>= 20 条）', (decisions.match(/^\|\s*D\d{2}\s*\|/gm) || []).length >= 20)
checker.check('决策记录覆盖数据层与中间件取舍', /MySQL/.test(decisions) && /Redis/.test(decisions) && /MinIO/.test(decisions))

const manual = read('docs/用户手册.md')
checker.check('用户手册含登录与角色说明', /登录/.test(manual) && /角色/.test(manual))
checker.check('用户手册含各功能模块操作步骤', ['驾驶舱', '价格监测', '预测', '预警', '情景', '报告'].every((key) => manual.includes(key)))

// ---------- 6. 截图证据 ----------
const shotsExist = existsSync(SCREENSHOT_DIR)
const shots = shotsExist ? readdirSync(SCREENSHOT_DIR).filter((name) => /\.(png|jpg|jpeg)$/i.test(name)) : []
checker.check('交付截图目录存在', shotsExist)
checker.check('交付截图数量 >= 18', shots.length >= 18, `实际 ${shots.length}`)
if (shots.length > 0) {
  const tiny = shots.filter((name) => statSync(path.join(SCREENSHOT_DIR, name)).size < 8000)
  checker.check('截图均为有效图片（> 8KB）', tiny.length === 0, `过小：${tiny.join(',')}`)
}

// ---------- 7. 界面占位残留 ----------
const viewsDir = path.join(ROOT, 'frontend', 'src', 'views')
const viewFiles = []
const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full)
    else if (entry.name.endsWith('.vue')) viewFiles.push(full)
  }
}
if (existsSync(viewsDir)) walk(viewsDir)
checker.check('前端页面文件齐全（>= 20 个视图）', viewFiles.length >= 20, `实际 ${viewFiles.length}`)
const placeholderViews = viewFiles.filter((file) => /页面建设中|功能开发中/.test(readFileSync(file, 'utf8')))
checker.check('无页面占位残留', placeholderViews.length === 0, placeholderViews.map((file) => path.relative(ROOT, file)).join(','))

// 路由与视图文件一一对应
const routerCode = read('frontend/src/router/index.ts')
const routeImports = [...routerCode.matchAll(/import\('@\/views\/([^']+)'\)/g)].map((match) => match[1].replace(/\.vue$/, ''))
const missingViews = routeImports.filter((rel) => !existsSync(path.join(ROOT, 'frontend', 'src', 'views', `${rel}.vue`)))
checker.check('路由引用的视图文件全部存在', routeImports.length >= 19 && missingViews.length === 0, `缺少 ${missingViews.join(',')}`)

// ---------- 8. 对外措辞与代码整洁 ----------
const deliveredDocs = ['README.md', 'docs/用户手册.md', 'docs/接口契约.md', 'docs/数据字典.md']
const forbidden = /演示|(?<![情])模拟|[Dd]emo|[Mm]ock/
const offenders = []
for (const file of deliveredDocs) {
  const content = read(file)
  const hit = content.match(forbidden)
  if (hit) offenders.push(`${file}:${hit[0]}`)
}
for (const file of viewFiles) {
  const content = readFileSync(file, 'utf8')
  const hit = content.match(forbidden)
  if (hit) offenders.push(`${path.relative(ROOT, file)}:${hit[0]}`)
}
checker.check('交付文档与界面无"演示/模拟数据"类措辞', offenders.length === 0, offenders.join(', '))

const packageJson = JSON.parse(read('package.json') || '{}')
checker.check('根 package.json 描述无演示字样', Boolean(packageJson.description) && !forbidden.test(packageJson.description), packageJson.description)

// E2E 覆盖全部路由
const e2eCode = exists('e2e') ? read('e2e/platform.spec.ts') + read('e2e/modules.spec.ts') : ''
const coveredRoutes = (routerCode.match(/path: '(\/[^']+)'/g) || []).length
checker.check('E2E 用例覆盖全部前端路由', coveredRoutes > 0 && routeImports.length >= 19 && e2eCode.length > 2000, `e2e 长度 ${e2eCode.length}`)

process.exit(checker.finish() ? 0 : 1)
