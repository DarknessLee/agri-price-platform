/** 种子数据脚本：重建 SQLite 数据库（默认包含模型训练）。 */
import { BACKEND_DIR, Checker, VENV_PY, ensureDirs, run } from './lib.mjs'

ensureDirs()
const args = process.argv.slice(2)
const checker = new Checker('种子数据重建')

const result = run(VENV_PY, ['-m', 'app.seed', '--reset', ...args], { cwd: BACKEND_DIR })
checker.check('seed 脚本执行成功', result.status === 0, `exit ${result.status}`)
process.exit(checker.finish() ? 0 : 1)
