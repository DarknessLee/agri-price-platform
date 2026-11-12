/** 构建门禁：前端类型检查 + 生产构建，并校验产物完整性。 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { Checker, FRONTEND_DIR, NPM, ROOT, ensureDirs, frontendEnv, run } from './lib.mjs'

ensureDirs()
const checker = new Checker('构建门禁（前端类型检查 + 打包）')
const buildEnv = frontendEnv()

const install = run(NPM, ['install', '--no-audit', '--no-fund'], { cwd: FRONTEND_DIR, stdio: 'inherit', env: buildEnv })
checker.check('frontend npm install 成功', install.status === 0, `exit ${install.status}`)

let build = run(NPM, ['run', 'build'], { cwd: FRONTEND_DIR, stdio: 'inherit', env: buildEnv })
if (build.status !== 0 && /esbuild/i.test(build.stderr || build.stdout)) {
  console.log('检测到 esbuild 安装脚本未执行，尝试重建…')
  run(NPM, ['rebuild', 'esbuild'], { cwd: FRONTEND_DIR, stdio: 'inherit', env: buildEnv })
  build = run(NPM, ['run', 'build'], { cwd: FRONTEND_DIR, stdio: 'inherit', env: buildEnv })
}
checker.check('vue-tsc 类型检查 + vite build 通过', build.status === 0, `exit ${build.status}`)

const dist = path.join(FRONTEND_DIR, 'dist')
const indexHtml = path.join(dist, 'index.html')
checker.check('dist/index.html 存在', existsSync(indexHtml))
checker.check('dist 资源目录存在', existsSync(path.join(dist, 'assets')))

if (existsSync(indexHtml)) {
  const html = readFileSync(indexHtml, 'utf8')
  checker.check('index.html 引用了打包后的入口脚本', /<script[^>]+src="(?:\.\/|\/)?assets\/index-[^"]+\.js"/.test(html))
  checker.check('index.html 使用 zh-CN 中文页面标题', /<html[^>]+lang="zh-CN"/.test(html) && html.includes('农产品价格'))
}

const assetsDir = path.join(dist, 'assets')
if (existsSync(assetsDir)) {
  const files = readFileSync(path.join(dist, 'index.html'), 'utf8')
  const match = files.match(/assets\/index-[^"]+\.js/)
  if (match) {
    const size = statSync(path.join(dist, match[0])).size
    checker.check('主包体积在合理范围（< 4MB）', size > 0 && size < 4 * 1024 * 1024, `${Math.round(size / 1024)} KB`)
  }
}

const rootFiles = ['README.md', 'STATUS.md', 'DECISIONS.md', 'PLAN-MATRIX.md', 'docs/接口契约.md']
for (const file of rootFiles) {
  checker.check(`交付文档存在：${file}`, existsSync(path.join(ROOT, file)))
}

process.exit(checker.finish() ? 0 : 1)
