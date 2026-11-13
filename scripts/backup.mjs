// 备份脚本：导出 MySQL 结构与数据、对象存储清单与关键行数，产物写入 .runtime/backups/
// 用法：node scripts/backup.mjs          备份到默认目录
//       node scripts/backup.mjs --keep   仅保留最近 7 份备份
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { BACKEND_DIR, ROOT, VENV_PY, ensureDirs, report } from './lib.mjs'

const startedAt = Date.now()
const MYSQL_CONTAINER = process.env.AGRI_MYSQL_CONTAINER || 'datasec-mysql'
const MYSQL_ROOT_PASSWORD = process.env.AGRI_MYSQL_ROOT_PASSWORD || 'DataSec_root_2026'
const MYSQL_DATABASE = process.env.AGRI_MYSQL_DATABASE || 'agri_price'
const BACKUP_DIR = path.join(ROOT, '.runtime', 'backups')
const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
const keep = process.argv.includes('--keep')

let passed = 0
let failed = 0

function check(name, fn) {
  try {
    const detail = fn()
    passed += 1
    console.log(`  PASS  ${name}${detail ? ` — ${detail}` : ''}`)
  } catch (error) {
    failed += 1
    console.log(`  FAIL  ${name} — ${error.message}`)
  }
}

function python(code, cwd = BACKEND_DIR) {
  const result = spawnSync(VENV_PY, ['-c', code], {
    cwd,
    encoding: 'utf8',
    timeout: 180000,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  if (result.status !== 0) throw new Error((result.stderr || '').trim().split(/\r?\n/).slice(-3).join(' | '))
  return (result.stdout || '').trim()
}

ensureDirs()
mkdirSync(BACKUP_DIR, { recursive: true })
const sqlFile = path.join(BACKUP_DIR, `${MYSQL_DATABASE}-${stamp}.sql`)
const manifestFile = path.join(BACKUP_DIR, `${MYSQL_DATABASE}-${stamp}-manifest.json`)

console.log(`== 数据备份（${MYSQL_DATABASE} → .runtime/backups）==`)

check('导出 MySQL 结构与数据（mysqldump）', () => {
  const dump = spawnSync(
    'docker',
    [
      'exec', MYSQL_CONTAINER, 'mysqldump',
      '-uroot', `-p${MYSQL_ROOT_PASSWORD}`,
      '--single-transaction', '--no-tablespaces', '--quick',
      '--default-character-set=utf8mb4',
      MYSQL_DATABASE,
    ],
    { encoding: 'buffer', timeout: 300000, maxBuffer: 1024 * 1024 * 512 },
  )
  if (dump.status !== 0) {
    throw new Error((dump.stderr || Buffer.from('')).toString('utf8').trim().split(/\r?\n/).slice(-2).join(' | '))
  }
  const bytes = dump.stdout || Buffer.alloc(0)
  if (bytes.length < 1024 * 64) throw new Error(`导出文件过小：${bytes.length} 字节`)
  writeFileSync(sqlFile, bytes)
  return `${(bytes.length / 1024 / 1024).toFixed(1)} MB → ${path.basename(sqlFile)}`
})

check('统计关键表行数', () => {
  const code = `
import json
from sqlalchemy import text
from app.database import SessionLocal
tables = ["price_record", "feature_record", "model_version", "model_run", "forecast_result",
          "alert_record", "alert_rule", "report", "scheduled_task", "scheduled_task_run",
          "sys_notification", "sys_email_log", "open_api_call", "audit_log", "sys_user"]
db = SessionLocal()
counts = {}
for name in tables:
    counts[name] = int(db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0)
print(json.dumps(counts, ensure_ascii=False))
`
  const counts = JSON.parse(python(code))
  writeFileSync(manifestFile, JSON.stringify({ database: MYSQL_DATABASE, created_at: stamp, counts }, null, 2), 'utf8')
  return `14 张关键表 / 价格 ${counts.price_record} 行`
})

check('导出对象存储清单', () => {
  const code = `
import json
from app import storage
state = storage.health()
items = []
if state.get("backend") == "minio":
    client = storage._resolve_client()
    if client is not None:
        for obj in client.list_objects(storage.STORAGE_BUCKET, recursive=True):
            items.append({"key": obj.object_name, "size": obj.size})
else:
    import os
    root = storage.STORAGE_ROOT
    for current, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(current, name)
            items.append({"key": os.path.relpath(full, root).replace(os.sep, "/"), "size": os.path.getsize(full)})
print(json.dumps({"backend": state.get("backend"), "items": items[:500], "total": len(items)}, ensure_ascii=False))
`
  const listing = JSON.parse(python(code))
  const objectsFile = path.join(BACKUP_DIR, `${MYSQL_DATABASE}-${stamp}-objects.json`)
  writeFileSync(objectsFile, JSON.stringify(listing, null, 2), 'utf8')
  return `${listing.backend} / ${listing.total} 个对象`
})

check('备份文件落盘校验', () => {
  for (const file of [sqlFile, manifestFile]) {
    if (!existsSync(file)) throw new Error(`缺少 ${path.basename(file)}`)
    if (statSync(file).size < 64) throw new Error(`${path.basename(file)} 过小`)
  }
  const files = readdirSync(BACKUP_DIR)
  return `${files.length} 个文件在 ${path.relative(ROOT, BACKUP_DIR)}`
})

if (keep) {
  const groups = readdirSync(BACKUP_DIR)
    .filter((name) => name.endsWith('.sql'))
    .sort()
    .reverse()
  const stale = groups.slice(7).map((name) => name.replace(/\.sql$/, ''))
  for (const prefix of stale) {
    for (const name of readdirSync(BACKUP_DIR)) {
      if (name.startsWith(prefix)) rmSync(path.join(BACKUP_DIR, name), { force: true })
    }
  }
  console.log(`  ..    已保留最近 ${Math.min(groups.length, 7)} 份备份`)
}

report(passed, failed, startedAt)
process.exit(failed === 0 ? 0 : 1)
