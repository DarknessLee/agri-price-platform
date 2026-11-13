// 基础设施就绪脚本：检查并启动本机 MySQL / Redis / MinIO / Mailpit 容器，幂等准备库与账号，最后做一次连通性校验。
// 用法：node scripts/infra.mjs
// 约定：优先复用已存在的容器（默认 datasec-mysql / datasec-redis / agri-minio / agri-mailpit），
//       MinIO 与 Mailpit 缺失时自动用 deploy/docker-compose.yml 拉起（走本机 Docker 镜像加速）。
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { ROOT, VENV_PY, report } from './lib.mjs'

const MYSQL_CONTAINER = process.env.AGRI_MYSQL_CONTAINER || 'datasec-mysql'
const REDIS_CONTAINER = process.env.AGRI_REDIS_CONTAINER || 'datasec-redis'
const MINIO_CONTAINER = process.env.AGRI_MINIO_CONTAINER || 'agri-minio'
const MAILPIT_CONTAINER = process.env.AGRI_MAILPIT_CONTAINER || 'agri-mailpit'
const MYSQL_ROOT_PASSWORD = process.env.AGRI_MYSQL_ROOT_PASSWORD || 'DataSec_root_2026'
const MYSQL_DATABASE = process.env.AGRI_MYSQL_DATABASE || 'agri_price'
const MYSQL_USER = process.env.AGRI_MYSQL_USER || 'agri'
const MYSQL_PASSWORD = process.env.AGRI_MYSQL_PASSWORD || 'Agri_2026'
const REDIS_PASSWORD = process.env.AGRI_REDIS_PASSWORD || 'DataSec_2026'
const MINIO_ACCESS_KEY = process.env.AGRI_MINIO_ACCESS_KEY || 'agri'
const MINIO_SECRET_KEY = process.env.AGRI_MINIO_SECRET_KEY || 'Agri_2026_minio'
const MINIO_BUCKET = process.env.AGRI_STORAGE_BUCKET || 'agri-artifacts'
const COMPOSE_FILE = `${ROOT}\\deploy\\docker-compose.yml`
// MinIO 镜像在部分网络下会被镜像站拒绝（denied），此时回退到官方服务端二进制，对外仍是同一 S3 接口（9000/9001）。
const MINIO_BINARY = `${ROOT}\\.runtime\\minio\\minio.exe`
const MINIO_DATA = `${ROOT}\\.runtime\\minio\\data`
const MINIO_LOG = `${ROOT}\\.runtime\\logs\\minio.log`
const MINIO_DOWNLOAD = 'https://dl.minio.org.cn/server/minio/release/windows-amd64/minio.exe'

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

// MinIO / Mailpit 属于平台自带基础设施：缺失时直接用 compose 拉起（镜像走本机加速站）
function ensureComposeService(service, container, label) {
  const { exists, state } = containerState(container)
  if (exists && state === 'running') return
  console.log(`  ..    ${label} 容器 ${container} 未运行，尝试通过 compose 启动（首次需拉取镜像）`)
  const up = docker(['compose', '-f', COMPOSE_FILE, 'up', '-d', service], { allowFail: true })
  if (!up.ok) {
    throw new Error(
      `${label} 启动失败：${(up.stderr || up.stdout).split(/\r?\n/).filter(Boolean).slice(-2).join(' | ')}`,
    )
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function httpOk(url, expect = 200) {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 4000)
    const response = await fetch(url, { signal: controller.signal })
    clearTimeout(timer)
    return response.status === expect
  } catch {
    return false
  }
}

// 优先用容器（镜像可达时）；镜像被镜像站拒绝时回退到官方 MinIO 服务端二进制，端口与凭据保持一致。
async function ensureMinio() {
  const { exists, state } = containerState(MINIO_CONTAINER)
  if (exists) {
    if (state !== 'running') docker(['start', MINIO_CONTAINER], { allowFail: true })
    if (await waitForPort('MinIO', 'http://127.0.0.1:9000/minio/health/live')) return 'container'
  } else {
    const up = docker(['compose', '-f', COMPOSE_FILE, 'up', '-d', 'agri-minio'], { allowFail: true, quiet: true })
    if (up.ok) {
      if (await waitForPort('MinIO', 'http://127.0.0.1:9000/minio/health/live')) return 'container'
      throw new Error(`MinIO 容器启动后健康检查未通过：${(up.stderr || '').slice(0, 200)}`)
    }
    console.log('  ..    MinIO 镜像不可用（镜像站拒绝），改用官方服务端二进制启动')
  }

  if (!existsSync(MINIO_BINARY)) {
    console.log('  ..    未找到 MinIO 二进制，正在下载（约 280MB，仅首次）')
    mkdirSync(`${ROOT}\\.runtime\\minio`, { recursive: true })
    const download = spawnSync('powershell', [
      '-NoProfile', '-Command',
      `$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '${MINIO_DOWNLOAD}' -OutFile '${MINIO_BINARY}' -UseBasicParsing`,
    ], { encoding: 'utf8', timeout: 900000 })
    if (download.status !== 0 || !existsSync(MINIO_BINARY)) {
      throw new Error(`MinIO 服务端二进制下载失败：${(download.stderr || '').trim().slice(0, 200)}`)
    }
  }

  if (await httpOk('http://127.0.0.1:9000/minio/health/live')) return 'binary'
  mkdirSync(MINIO_DATA, { recursive: true })
  mkdirSync(`${ROOT}\\.runtime\\logs`, { recursive: true })
  const child = spawn(MINIO_BINARY, ['server', MINIO_DATA, '--address', '127.0.0.1:9000', '--console-address', '127.0.0.1:9001'], {
    cwd: ROOT,
    detached: true,
    stdio: 'ignore',
    env: { ...process.env, MINIO_ROOT_USER: MINIO_ACCESS_KEY, MINIO_ROOT_PASSWORD: MINIO_SECRET_KEY },
  })
  child.unref()
  if (!(await waitForPort('MinIO', 'http://127.0.0.1:9000/minio/health/live'))) {
    throw new Error('MinIO 二进制启动失败，详见 .runtime/logs 或手动执行 .runtime\\minio\\minio.exe server .runtime\\minio\\data')
  }
  return 'binary'
}

async function waitForPort(label, url, { attempts = 40, delay = 1000 } = {}) {
  for (let index = 0; index < attempts; index += 1) {
    if (await httpOk(url)) return true
    await sleep(delay)
  }
  console.log(`  ..    ${label} 在 ${(attempts * delay) / 1000}s 内未就绪`)
  return false
}

async function waitUntil(label, probe, { attempts = 60, delay = 1000 } = {}) {
  for (let index = 0; index < attempts; index += 1) {
    if (probe()) return true
    await sleep(delay)
  }
  throw new Error(`${label} 在 ${attempts * delay / 1000}s 内未就绪`)
}

console.log('== 基础设施就绪检查（MySQL / Redis / MinIO / Mailpit）==')
check('Docker 服务可用', () => docker(['version', '--format', '{{.Server.Version}}']).stdout)

ensureContainer(MYSQL_CONTAINER, 'MySQL')
ensureContainer(REDIS_CONTAINER, 'Redis')
const minioMode = await ensureMinio().catch((error) => {
  console.log(`  FAIL  MinIO 服务就绪 — ${error.message}`)
  failed += 1
  return null
})
if (minioMode) {
  passed += 1
  console.log(`  PASS  MinIO 服务就绪 — 9000/9001（${minioMode === 'container' ? '容器' : '服务端二进制'}）`)
}
check('Mailpit 容器就绪', () => {
  ensureComposeService('agri-mailpit', MAILPIT_CONTAINER, 'Mailpit')
  return MAILPIT_CONTAINER
})

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

check('应用侧连通性（SQLAlchemy + redis-py + MinIO + SMTP）', () => {
  const probe = `
import json
from app.config import DATABASE_URL, REDIS_URL, DB_BACKEND, MAIL_HOST, MAIL_PORT
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
try:
    import urllib3
    from minio import Minio
    http_client = urllib3.PoolManager(timeout=urllib3.Timeout(connect=3.0, read=8.0))
    client = Minio("127.0.0.1:9000", access_key="${MINIO_ACCESS_KEY}", secret_key="${MINIO_SECRET_KEY}", secure=False, http_client=http_client)
    if not client.bucket_exists("${MINIO_BUCKET}"):
        client.make_bucket("${MINIO_BUCKET}")
    import io
    client.put_object("${MINIO_BUCKET}", "health/probe.txt", io.BytesIO(b"ok"), length=2)
    payload["minio"] = True
    payload["minio_bucket"] = "${MINIO_BUCKET}"
except Exception as exc:
    payload["minio"] = False
    payload["minio_error"] = str(exc)[:160]
try:
    import smtplib
    probe = smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=4)
    code = probe.noop()[0]
    probe.quit()
    payload["smtp"] = code == 250
except Exception as exc:
    payload["smtp"] = False
    payload["smtp_error"] = str(exc)[:160]
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
  if (!payload.minio) throw new Error(`MinIO 连接失败：${payload.minio_error || '127.0.0.1:9000'}`)
  const mailText = payload.smtp ? 'SMTP OK' : `SMTP 不可用（${payload.smtp_error || '未连通'}）`
  return `${payload.backend} / MySQL OK / Redis ${payload.redis_version} / MinIO ${payload.minio_bucket} / ${mailText}`
})

check('MinIO 控制台可访问', () => {
  const probe = `
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:9001/", timeout=5) as response:
        print(response.status)
except Exception as exc:
    raise SystemExit(f"控制台不可访问：{exc}")
`
  const out = spawnSync(VENV_PY, ['-c', probe], { encoding: 'utf8', timeout: 30000 })
  if (out.status !== 0) throw new Error((out.stderr || '').trim().split(/\r?\n/).pop())
  return `9001 → ${(out.stdout || '').trim()}`
})

check('Mailpit 收件箱可访问', () => {
  const probe = `
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8025/api/v1/messages?limit=1", timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))
print(payload.get("total", 0))
`
  const out = spawnSync(VENV_PY, ['-c', probe], { encoding: 'utf8', timeout: 30000 })
  if (out.status !== 0) throw new Error((out.stderr || '').trim().split(/\r?\n/).pop())
  return `8025 → 已收 ${(out.stdout || '').trim()} 封`
})

console.log(failed === 0 ? '\n基础设施已就绪：可执行 npm run seed 初始化数据，npm run dev 启动前后端。' : '\n基础设施未就绪，请检查上面的失败项。')
report(passed, failed, startedAt)
process.exit(failed === 0 ? 0 : 1)
