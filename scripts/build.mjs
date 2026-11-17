/** 构建门禁：PC 前端 + 移动 H5 的类型检查与生产构建，并校验产物完整性。 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { Checker, FRONTEND_DIR, H5_DIR, NPM, ROOT, ensureDirs, frontendEnv, run } from './lib.mjs'

ensureDirs()
const checker = new Checker('构建门禁（PC 前端 + 移动 H5 类型检查 + 打包）')

function buildApp(name, dir) {
  const env = frontendEnv(dir)
  const install = run(NPM, ['install', '--no-audit', '--no-fund'], { cwd: dir, stdio: 'inherit', env })
  checker.check(`${name} npm install 成功`, install.status === 0, `exit ${install.status}`)

  let build = run(NPM, ['run', 'build'], { cwd: dir, stdio: 'inherit', env })
  if (build.status !== 0 && /esbuild/i.test(build.stderr || build.stdout)) {
    console.log(`[${name}] 检测到 esbuild 安装脚本未执行，尝试重建…`)
    run(NPM, ['rebuild', 'esbuild'], { cwd: dir, stdio: 'inherit', env })
    build = run(NPM, ['run', 'build'], { cwd: dir, stdio: 'inherit', env })
  }
  checker.check(`${name} vue-tsc 类型检查 + vite build 通过`, build.status === 0, `exit ${build.status}`)
  return path.join(dir, 'dist')
}

const dist = buildApp('PC 前端', FRONTEND_DIR)
const indexHtml = path.join(dist, 'index.html')
checker.check('PC dist/index.html 存在', existsSync(indexHtml))
checker.check('PC dist 资源目录存在', existsSync(path.join(dist, 'assets')))

if (existsSync(indexHtml)) {
  const html = readFileSync(indexHtml, 'utf8')
  checker.check('PC index.html 引用了打包后的入口脚本', /<script[^>]+src="(?:\.\/|\/)?assets\/index-[^"]+\.js"/.test(html))
  checker.check('PC index.html 使用 zh-CN 中文页面标题', /<html[^>]+lang="zh-CN"/.test(html) && html.includes('农产品价格'))
}

const assetsDir = path.join(dist, 'assets')
if (existsSync(assetsDir)) {
  const html = readFileSync(path.join(dist, 'index.html'), 'utf8')
  const match = html.match(/assets\/index-[^"]+\.js/)
  if (match) {
    const size = statSync(path.join(dist, match[0])).size
    checker.check('PC 主包体积在合理范围（< 4MB）', size > 0 && size < 4 * 1024 * 1024, `${Math.round(size / 1024)} KB`)
  }
}

const h5Dist = buildApp('移动 H5', H5_DIR)
const h5Index = path.join(h5Dist, 'index.html')
checker.check('H5 dist/index.html 存在', existsSync(h5Index))
checker.check('H5 dist 资源目录存在', existsSync(path.join(h5Dist, 'assets')))

if (existsSync(h5Index)) {
  const html = readFileSync(h5Index, 'utf8')
  checker.check('H5 index.html 引用了打包后的入口脚本', /<script[^>]+src="\/m\/assets\/index-[^"]+\.js"/.test(html))
  checker.check('H5 index.html 使用 zh-CN 中文页面标题', /<html[^>]+lang="zh-CN"/.test(html) && html.includes('农产品价格'))
  checker.check('H5 声明移动端 viewport', /name="viewport"[^>]+width=device-width/.test(html))
}

const h5Assets = path.join(h5Dist, 'assets')
if (existsSync(h5Assets)) {
  const html = readFileSync(h5Index, 'utf8')
  const match = html.match(/\/m\/assets\/index-[^"]+\.js/)
  if (match) {
    const size = statSync(path.join(h5Dist, 'assets', path.basename(match[0]))).size
    checker.check('H5 主包体积在合理范围（< 3MB）', size > 0 && size < 3 * 1024 * 1024, `${Math.round(size / 1024)} KB`)
  }
}

const rootFiles = ['README.md', 'STATUS.md', 'DECISIONS.md', 'PLAN-MATRIX.md', 'docs/接口契约.md']
for (const file of rootFiles) {
  checker.check(`交付文档存在：${file}`, existsSync(path.join(ROOT, file)))
}

process.exit(checker.finish() ? 0 : 1)
