// 生成交付物 12：源码与部署包
// 用法：node scripts/package.mjs
// 产物：deliverables/12-源码与部署包.zip
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const OUT_DIR = path.join(ROOT, 'deliverables');
const STAGE = path.join(OUT_DIR, '.pkg');
const APP = path.join(STAGE, 'agri-price-platform');
const ZIP = path.join(OUT_DIR, '12-源码与部署包.zip');

const SKIP_DIRS = new Set(['node_modules', '.venv', '.git', '.runtime', '.build-tmp', '__pycache__', '.pytest_cache', 'test-results', '.pkg']);

/** 需要进入交付包的顶层条目 */
const ENTRIES = [
  'README.md',
  'STATUS.md',
  'DECISIONS.md',
  'PLAN-MATRIX.md',
  'package.json',
  'package-lock.json',
  'playwright.config.ts',
  'backend/app',
  'backend/requirements.txt',
  'frontend/src',
  'frontend/package.json',
  'frontend/package-lock.json',
  'frontend/vite.config.ts',
  'frontend/tsconfig.json',
  'frontend/index.html',
  'frontend/dist',
  'scripts',
  'e2e',
  'deploy',
  'docs',
  'deliverables',
];

function copyTree(src, dest) {
  const st = fs.statSync(src);
  if (st.isDirectory()) {
    const base = path.basename(src);
    if (SKIP_DIRS.has(base)) return;
    fs.mkdirSync(dest, { recursive: true });
    for (const name of fs.readdirSync(src)) {
      if (SKIP_DIRS.has(name)) continue;
      copyTree(path.join(src, name), path.join(dest, name));
    }
    return;
  }
  if (/\.(pyc|pyo|log|tmp)$/i.test(src)) return;
  // 交付目录内的压缩包自身不重复进包
  if (/12-源码与部署包\.zip$/i.test(src)) return;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

function sizeOf(dir) {
  let total = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    total += entry.isDirectory() ? sizeOf(full) : fs.statSync(full).size;
  }
  return total;
}

const startedAt = Date.now();
let passed = 0;
let failed = 0;

function check(name, ok, detail = '') {
  if (ok) {
    passed += 1;
    console.log(`  [PASS] ${name}${detail ? ` — ${detail}` : ''}`);
  } else {
    failed += 1;
    console.log(`  [FAIL] ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

console.log('[package] 收集交付文件…');
fs.rmSync(STAGE, { recursive: true, force: true });
fs.mkdirSync(APP, { recursive: true });

for (const entry of ENTRIES) {
  const src = path.join(ROOT, entry);
  if (!fs.existsSync(src)) {
    console.log(`  [WARN] 缺少 ${entry}，已跳过`);
    continue;
  }
  copyTree(src, path.join(APP, entry));
}

// 交付目录内的压缩包自身与暂存目录不进入包
fs.rmSync(path.join(APP, 'deliverables', '12-源码与部署包.zip'), { force: true });
fs.rmSync(path.join(APP, 'deliverables', '.pkg'), { recursive: true, force: true });

const fileCount = (() => {
  let count = 0;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else count += 1;
    }
  };
  walk(APP);
  return count;
})();
const rawSize = sizeOf(APP);

console.log(`[package] 暂存完成：${fileCount} 个文件，${(rawSize / 1024 / 1024).toFixed(1)} MB`);

fs.rmSync(ZIP, { force: true });
execFileSync(
  'powershell',
  [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    `Compress-Archive -Path '${APP}' -DestinationPath '${ZIP}' -CompressionLevel Optimal -Force`,
  ],
  { stdio: 'inherit' },
);

check('压缩包已生成', fs.existsSync(ZIP));
const zipSize = fs.existsSync(ZIP) ? fs.statSync(ZIP).size : 0;
check('压缩包大小合理（>5MB 且 <300MB）', zipSize > 5 * 1024 * 1024 && zipSize < 300 * 1024 * 1024, `${(zipSize / 1024 / 1024).toFixed(1)} MB`);
check('包含后端代码', fs.existsSync(path.join(APP, 'backend', 'app', 'main.py')));
check('包含前端代码与构建产物', fs.existsSync(path.join(APP, 'frontend', 'src', 'main.ts')) && fs.existsSync(path.join(APP, 'frontend', 'dist', 'index.html')));
check('包含部署编排', fs.existsSync(path.join(APP, 'deploy', 'docker-compose.yml')));
check('包含门禁脚本', fs.existsSync(path.join(APP, 'scripts', 'lib.mjs')) && fs.existsSync(path.join(APP, 'scripts', 'gate.mjs')));
check('包含交付文档', fs.existsSync(path.join(APP, 'deliverables', '00-交付物清单.md')));
check('不包含依赖目录', !fs.existsSync(path.join(APP, 'node_modules')) && !fs.existsSync(path.join(APP, '.venv')));

fs.rmSync(STAGE, { recursive: true, force: true });

const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);
console.log(`[package] 产物：${path.relative(ROOT, ZIP)}（${(zipSize / 1024 / 1024).toFixed(1)} MB，${fileCount} 个文件）`);
console.log(`RESULT=${failed === 0 ? 'PASS' : 'FAIL'} passed=${passed} failed=${failed} 用时=${seconds}s`);
process.exit(failed === 0 ? 0 : 1);
