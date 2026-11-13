// 校验开发书第 12 节 13 项交付物
// 用法：node scripts/deliverables.mjs
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const DIR = path.join(ROOT, 'deliverables');

const DOCS = [
  { no: '01', file: '01-需求规格说明书.md', minLines: 100, must: ['需求规格', '验收判据', '功能需求'] },
  { no: '02', file: '02-系统设计说明书.md', minLines: 120, must: ['总体架构', '技术选型', '模块划分'] },
  { no: '03', file: '03-数据库设计.md', minLines: 120, must: ['索引', '枚举', '保留策略'] },
  { no: '04', file: '04-接口文档.md', minLines: 140, must: ['错误码', '权限点', '示例'] },
  { no: '05', file: '05-数据治理规范.md', minLines: 110, must: ['质量规则', '处置', '审计'] },
  { no: '06', file: '06-模型训练与回测报告.md', minLines: 120, must: ['MAPE', '回测', '漂移'] },
  { no: '07', file: '07-测试报告.md', minLines: 120, must: ['门禁', '缺陷', '结论'] },
  { no: '08', file: '08-安全与合规说明.md', minLines: 110, must: ['认证', '授权', '审计'] },
  { no: '09', file: '09-部署运维手册.md', minLines: 120, must: ['端口', '备份', '故障'] },
  { no: '10', file: '10-用户操作手册.md', minLines: 120, must: ['登录', '预测', '预警'] },
  { no: '11', file: '11-培训材料.md', minLines: 100, must: ['大纲', '练习', '考核'] },
  { no: '12', file: '12-源码与部署包.zip', minLines: 0, must: [] },
  { no: '13', file: '13-验收报告.md', minLines: 90, must: ['验收范围', '验收结论', '遗留'] },
];

const FORBIDDEN = /演示|(?<![情])模拟|[Dd]emo|[Mm]ock/;
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

console.log('[deliverables] 校验交付物目录');
check('交付物清单存在', fs.existsSync(path.join(DIR, '00-交付物清单.md')), 'deliverables/00-交付物清单.md');

for (const doc of DOCS) {
  const full = path.join(DIR, doc.file);
  const exists = fs.existsSync(full);
  if (!exists) {
    check(`交付物 ${doc.no} 存在`, false, doc.file);
    continue;
  }
  if (doc.file.endsWith('.zip')) {
    const size = fs.statSync(full).size;
    check(`交付物 ${doc.no} 压缩包`, size > 5 * 1024 * 1024, `${(size / 1024 / 1024).toFixed(1)} MB`);
    continue;
  }
  const text = fs.readFileSync(full, 'utf8');
  const lines = text.split('\n').length;
  check(`交付物 ${doc.no} 存在且行数达标`, lines >= doc.minLines, `${doc.file} ${lines} 行 ≥ ${doc.minLines}`);
  check(`交付物 ${doc.no} 含关键章节`, doc.must.every((word) => text.includes(word)), doc.must.join(' / '));
  check(`交付物 ${doc.no} 含表格`, (text.match(/^\|/gm) || []).length >= 8, '表格行数充足');
  check(`交付物 ${doc.no} 无禁用措辞`, !FORBIDDEN.test(text));
}

const readme = path.join(ROOT, 'README.md');
check('README 引用交付物目录', fs.existsSync(readme) && fs.readFileSync(readme, 'utf8').includes('deliverables'));

const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);
console.log(`RESULT=${failed === 0 ? 'PASS' : 'FAIL'} passed=${passed} failed=${failed} 用时=${seconds}s`);
process.exit(failed === 0 ? 0 : 1);
