/**
 * 门禁脚本公共工具：路径、进程管理、HTTP 请求、结果行输出。
 * 所有门禁脚本最后一行固定输出：RESULT=PASS|FAIL passed=N failed=M 用时=S
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, openSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = fileURLToPath(new URL('..', import.meta.url))
export const BACKEND_DIR = path.join(ROOT, 'backend')
export const FRONTEND_DIR = path.join(ROOT, 'frontend')
export const H5_DIR = path.join(ROOT, 'h5')
export const RUNTIME_DIR = path.join(ROOT, '.runtime')
export const LOG_DIR = path.join(RUNTIME_DIR, 'logs')
export const ARTIFACT_DIR = path.join(RUNTIME_DIR, 'artifacts')
export const SCREENSHOT_DIR = path.join(ROOT, 'docs', 'screenshots')
export const BASE_URL = process.env.API_BASE_URL || 'http://127.0.0.1:8017'
export const FRONTEND_URL = process.env.FRONTEND_URL || 'http://127.0.0.1:5177'

export const VENV_PY = path.join(
  ROOT,
  '.venv',
  'Scripts',
  process.platform === 'win32' ? 'python.exe' : 'python',
)

export const NPM = process.platform === 'win32' ? 'npm.cmd' : 'npm'

export function ensureDirs() {
  for (const dir of [RUNTIME_DIR, LOG_DIR, ARTIFACT_DIR]) {
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
  }
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function run(cmd, args, options = {}) {
  const started = Date.now()
  const result = spawnSync(cmd, args, {
    cwd: options.cwd || ROOT,
    stdio: options.stdio || 'inherit',
    shell: process.platform === 'win32' && /\.(cmd|bat)$/i.test(cmd),
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1', ...(options.env || {}) },
    timeout: options.timeout || 0,
  })
  return { status: result.status ?? 1, stdout: result.stdout || '', stderr: result.stderr || '', ms: Date.now() - started }
}

export function runCapture(cmd, args, options = {}) {
  return run(cmd, args, { ...options, stdio: 'pipe' })
}

export function report(passed, failed, startedAt) {
  const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1)
  const ok = failed === 0 && passed > 0
  console.log(`RESULT=${ok ? 'PASS' : 'FAIL'} passed=${passed} failed=${failed} 用时=${elapsed}s`)
  return ok
}

export function requireVenv() {
  if (!existsSync(VENV_PY)) {
    console.error(`缺少 Python 虚拟环境：${VENV_PY}`)
    console.error('请先执行：python -m venv .venv 并安装 backend/requirements.txt')
    process.exit(2)
  }
  return VENV_PY
}

/** 前端构建临时目录：规避本机系统 Temp 清理被拒导致 esbuild 失败。 */
export function frontendEnv(dir = FRONTEND_DIR) {
  const tmp = path.join(dir, '.tmp')
  if (!existsSync(tmp)) mkdirSync(tmp, { recursive: true })
  return { TMP: tmp, TEMP: tmp }
}

export function requireNodeModules() {
  if (!existsSync(path.join(ROOT, 'node_modules', '@playwright', 'test'))) {
    console.error('缺少根目录 node_modules，请先执行 npm install')
    process.exit(2)
  }
}

/** 启动后端 uvicorn，返回 { proc, stop, logs }。 */
export async function startBackend({ port = 8017, logFile } = {}) {
  ensureDirs()
  requireVenv()
  const logPath = logFile || path.join(LOG_DIR, 'backend-gate.log')
  const fd = openSync(logPath, 'w')
  const proc = spawn(
    VENV_PY,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
    {
      cwd: BACKEND_DIR,
      stdio: ['ignore', fd, fd],
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      windowsHide: true,
    },
  )

  const stop = () => stopProcess(proc)
  const ready = await waitHealth(180000, port)
  if (!ready) {
    stop()
    throw new Error(`后端启动失败，详见日志：${logPath}`)
  }
  return { proc, stop, logPath }
}

export function stopProcess(proc) {
  if (!proc || proc.killed) return
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' })
    } else {
      proc.kill('SIGTERM')
    }
  } catch {
    /* ignore */
  }
}

export async function waitHealth(timeoutMs = 180000, port = 8017) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (response.ok) {
        const body = await response.json()
        if (body?.code === '0' || body?.status === 'ok') return true
      }
    } catch {
      /* 服务尚未就绪 */
    }
    await sleep(1200)
  }
  return false
}

/** 调用后端接口，返回 { status, body, data }，不抛异常。 */
export async function callApi(pathname, { method = 'GET', token, body, headers, timeout = 60000 } = {}) {
  const url = pathname.startsWith('http') ? pathname : `${BASE_URL}${pathname}`
  const response = await fetch(url, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(headers || {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeout),
  })
  let payload = null
  const text = await response.text()
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = { raw: text.slice(0, 500) }
  }
  return {
    status: response.status,
    body: payload,
    data: payload?.data,
    code: payload?.code == null ? undefined : String(payload.code),
    headers: response.headers,
  }
}

export async function login(username = 'admin', password = 'Admin@2026') {
  const result = await callApi('/api/auth/login', { method: 'POST', body: { username, password } })
  if (result.code !== '0' || !result.data?.token) {
    throw new Error(`登录失败：${username} ${JSON.stringify(result.body).slice(0, 300)}`)
  }
  return result.data
}

/** 简单断言收集器。 */
export class Checker {
  constructor(title) {
    this.title = title
    this.passed = 0
    this.failed = 0
    this.failures = []
    this.startedAt = Date.now()
    console.log(`\n=== ${title} ===`)
  }

  check(name, condition, detail = '') {
    if (condition) {
      this.passed += 1
      console.log(`  [PASS] ${name}`)
    } else {
      this.failed += 1
      const line = detail ? `${name} :: ${detail}` : name
      this.failures.push(line)
      console.log(`  [FAIL] ${line}`)
    }
    return Boolean(condition)
  }

  equal(name, actual, expected) {
    return this.check(name, actual === expected, `期望 ${JSON.stringify(expected)} 实际 ${JSON.stringify(actual)}`)
  }

  truthy(name, value) {
    return this.check(name, Boolean(value), `实际 ${JSON.stringify(value)?.slice(0, 200)}`)
  }

  finish() {
    return report(this.passed, this.failed, this.startedAt)
  }
}
