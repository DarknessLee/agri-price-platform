/** 本地开发：同时启动后端（8017）、电脑端前端（5177）与移动 H5 开发服务（5178）。 */
import { spawn } from 'node:child_process'
import { openSync } from 'node:fs'
import path from 'node:path'
import { BACKEND_DIR, FRONTEND_DIR, H5_DIR, LOG_DIR, NPM, ROOT, VENV_PY, ensureDirs, sleep, waitHealth } from './lib.mjs'

ensureDirs()
const backendLog = openSync(path.join(LOG_DIR, 'backend-dev.log'), 'w')
const children = []

function shutdown() {
  for (const child of children) {
    if (!child.killed) {
      try {
        child.kill('SIGTERM')
      } catch {
        /* ignore */
      }
    }
  }
  process.exit(0)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

const backend = spawn(
  VENV_PY,
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8017', '--reload', '--log-level', 'info'],
  {
    cwd: BACKEND_DIR,
    stdio: ['ignore', backendLog, backendLog],
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    windowsHide: true,
  },
)
children.push(backend)
console.log(`后端启动中：http://127.0.0.1:8017 （日志 ${path.join(LOG_DIR, 'backend-dev.log')}）`)

const ready = await waitHealth(120000, 8017)
console.log(ready ? '后端已就绪' : '后端健康检查超时，请查看日志')

const frontend = spawn(NPM, ['run', 'dev'], {
  cwd: FRONTEND_DIR,
  stdio: 'inherit',
  shell: process.platform === 'win32',
  windowsHide: true,
})
children.push(frontend)

// 移动 H5：独立 Vite 服务（5178，/m/ 前缀，/api 代理到 8017）
const h5 = spawn(NPM, ['run', 'dev'], {
  cwd: H5_DIR,
  stdio: 'inherit',
  shell: process.platform === 'win32',
  windowsHide: true,
})
children.push(h5)

await sleep(1500)
console.log('\n电脑端：http://127.0.0.1:5177')
console.log('移动 H5：http://127.0.0.1:5178/m/')
console.log('默认账号：admin / Admin@2026')
console.log('按 Ctrl+C 停止全部进程。\n')

await new Promise((resolve) => {
  frontend.on('exit', resolve)
  h5.on('exit', resolve)
})
shutdown()
