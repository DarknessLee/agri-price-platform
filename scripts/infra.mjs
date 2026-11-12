// 数据服务就绪脚本：检查并启动本机 MySQL / Redis 容器，幂等准备库与账号，最后做一次连通性校验。
// 用法：node scripts/infra.mjs
// 约定：优先复用已存在的容器（默认 datasec-mysql / datasec-redis），缺失时提示用 deploy/docker-compose.yml 启动。
import { spawnSync } from 'node:child_process'
import { ROOT, VENV_PY, report } from './lib.mjs'

const MYSQL_CONTAINER = process.env.AGRI_MYSQL_CONTAINER || 'datasec-mysql'
const REDIS_CONTAINER = process.env.AGRI_REDIS_CONTAINER || 'datasec-redis'
const MYSQL_ROOT_PASSWORD = process.env.AGRI_MYSQL_ROOT_PASSWORD || 'DataSec_root_2026'
const MYSQL_DATABASE = process.env.AGRI_MYSQL_DATABASE || 'agri_price'
const MYSQL_USER = process.env.AGRI_MYSQL_USER || 'agri'
const MYSQL_PASSWORD = process.env.AGRI_MYSQL_PASSWORD || 'Agri_2026'
const REDIS_PASSWORD = process.env.AGRI_REDIS_PASSWORD || 'DataSec_2026'

const startedAt = Date.now()
let passed = 0
let failed = 0

function docker(args, { allowFail = false, quiet = false } = {}) {
  const result = spawnSync('docker', args, { cwd: ROOT, encoding: 'utf8', timeout: 180000 })
  const ok = result.status === 0
  if (!ok && !allowFail) {
    const detail = `${result.stdout || ''}${result.stderr || ''}`.trim()
    throw new Error(`docker ${args.join(' ')} 执行失败：${detail}`)
  }
  if (!quiet && !ok) {
    process.stdout.write(`  ! docker ${args.join(' ')}: ${(result.stderr || '').trim().slice(0, 300)}\n`)
  }
  return { ok, stdout: (result.stdout || '').trim(), stderr: (result.stderr || '').trim() }
}

function check(name, fn) {
  try {
    const detail = fn()
    passed += 1
    console.log(`  PASS  ${name}${detail ? ` — ${detail}` : ''}`)
    return true
  } catch (error) {
    failed += 1
    console.log(`  FAIL  ${name} — ${error.message}`)
    return false
  }
}

function containerState(name) {
  const listed = docker(['ps', '-a', '--filter', `name=^${name}$`, '--format', '{{.Names}}\t{{.State}}'], { quiet: true })
  if (!listed.ok || !listed.stdout) return { exists: false, state: 'missing' }
  const [line] = listed.stdout.split(/\r?\n/)
  const [, state = 'unknown'] = line.split('\t')
  return { exists: true, state }
}

function ensureContainer(name, label) {
  const { exists, state } = containerState(name)
  if (!exists) {
    throw new Error(
      `${label} 容器 ${name} 不存在，请先执行：docker compose -f deploy/docker-compose.yml up -d（或 docker run 方式启动同名容器）`,
    )
  }
  if (state !== 'running') {
    console.log(`  ..    ${label} 容器 ${name} 当前 ${state}，正在启动`)
    docker(['start', name])
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitUntil(label, probe, { attempts = 60, delay = 1000 } = {}) {
  for (let index = 0; index < attempts; index += 1) {
    if (probe()) return true
    await sleep(delay)
  }
  throw new Error(`${label} 在 ${attempts * delay / 1000}s 内未就绪`)
}

console.log('== 数据服务就绪检查（MySQL / Redis）==')
check('Docker 服务可用', () => docker(['version', '--format', '{{.Server.Version}}']).stdout)

ensureContainer(MYSQL_CONTAINER, 'MySQL')
ensureContainer(REDIS_CONTAINER, 'Redis')

await waitUntil('MySQL 端口', () =>
  docker(
    ['exec', MYSQL_CONTAINER, 'mysqladmin', 'ping', '-h', '127.0.0.1', '-uroot', `-p${MYSQL_ROOT_PASSWORD}`],
    { allowFail: true, quiet: true },
  ).ok,
)
check('MySQL 容器存活', () => {
  const out = docker([
    'exec', MYSQL_CONTAINER, 'mysql', '-uroot', `-p${MYSQL_ROOT_PASSWORD}`, '-N', '-e',
    'SELECT VERSION();',
  ], { allowFail: true })
  if (!out.ok) throw new Error(out.stderr.split(/\r?\n/).pop())
  return out.stdout.split(/\r?\n/).pop()
})

await waitUntil('Redis 端口', () =>
  docker(['exec', REDIS_CONTAINER, 'redis-cli', '-a', REDIS_PASSWORD, 'ping'], { allowFail: true, quiet: true }).stdout
    .includes('PONG'),
)
check('Redis 容器存活', () => {
  const out = docker(['exec', REDIS_CONTAINER, 'redis-cli', '-a', REDIS_PASSWORD, 'INFO', 'server'], { allowFail: true })
  const version = /redis_version:([^\r\n]+)/.exec(out.stdout)?.[1]
  if (!version) throw new Error('无法读取 redis_version')
  return version
})

check('业务库与账号就绪', () => {
  const sql = [
    `CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;`,
    `CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';`,
    `ALTER USER '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';`,
    `GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';`,
    'FLUSH PRIVILEGES;',
  ].join(' ')
  const out = docker(['exec', MYSQL_CONTAINER, 'mysql', '-uroot', `-p${MYSQL_ROOT_PASSWORD}`, '-e', sql], { allowFail: true })
  if (!out.ok) throw new Error(out.stderr.split(/\r?\n/).filter((line) => line && !line.includes('Using a password')).join(' | '))
  return `${MYSQL_DATABASE} / ${MYSQL_USER}`
})

check('应用侧连通性（SQLAlchemy + redis-py）', () => {
  const probe = `
import json
from app.config import DATABASE_URL, REDIS_URL, DB_BACKEND
from app.database import engine, ping
import redis
payload = {"backend": DB_BACKEND, "db": bool(ping())}
try:
    client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    payload["redis"] = bool(client.ping())
    payload["redis_version"] = client.info("server").get("redis_version")
except Exception as exc:
    payload["redis"] = False
    payload["redis_error"] = str(exc)[:160]
print(json.dumps(payload, ensure_ascii=False))
`
  const out = spawnSync(VENV_PY, ['-c', probe], {
    cwd: `${ROOT}\\backend`,
    encoding: 'utf8',
    timeout: 120000,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  if (out.status !== 0) throw new Error((out.stderr || '').trim().split(/\r?\n/).slice(-3).join(' | '))
  const line = (out.stdout || '').trim().split(/\r?\n/).pop()
  const payload = JSON.parse(line)
  if (!payload.db) throw new Error(`数据库连接失败：${DATABASE_URL}`)
  if (!payload.redis) throw new Error(`Redis 连接失败：${payload.redis_error || REDIS_URL}`)
  return `${payload.backend} / MySQL OK / Redis ${payload.redis_version}`
})

console.log(failed === 0 ? '\n数据服务已就绪：可执行 npm run seed 初始化数据，npm run dev 启动前后端。' : '\n数据服务未就绪，请检查上面的失败项。')
report(passed, failed, startedAt)
process.exit(failed === 0 ? 0 : 1)
