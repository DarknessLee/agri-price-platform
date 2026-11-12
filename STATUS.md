# 当前状态（STATUS）

- 项目/版本：农产品价格预测分析系统 V1.0（`agri-price-platform`）
- 当前阶段：M1 完成（功能齐备、五道门禁通过、门禁证据已归档）
- 最近更新：2026-11-12
- 当前分支：`main`（本地仓库，无远端；分批提交）
- 运行入口：`npm run dev` → 前端 `http://127.0.0.1:5177`、后端 `http://127.0.0.1:8017`
- 数据重建：`npm run seed`（清库并重建 84,660 条价格、31,380 条特征、120 个模型版本与业务数据）
- 内置账号：`admin/Admin@2026`、`analyst01/Analyst@2026`、`operator01/Operator@2026`、`viewer01/Viewer@2026`

## 最近验收

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 构建 | `npm run build` | `RESULT=PASS passed=12 failed=0 用时=20.7s` |
| 数据库 | `npm run db:validate` | `RESULT=PASS passed=34 failed=0 用时=0.1s` |
| 接口 | `npm run test:api` | `RESULT=PASS passed=156 failed=0 用时=10.3s` |
| 端到端 | `npm run test:e2e` | `RESULT=PASS passed=18 failed=0 用时=52.0s` |
| 文档 | `npm run check:docs` | `RESULT=PASS passed=42 failed=0 用时=0.0s` |

一键复跑：`npm run gate`（串行执行五道门禁，任一失败即停止并保留日志于 `.runtime/artifacts/`）。

## 交付物

- 代码：`backend/`（FastAPI，24 表、12 路由模块、8 服务模块）、`frontend/`（Vue3 + TS，22 视图）、`scripts/`（门禁与启动脚本）、`e2e/`（Playwright 用例）
- 文档：`README.md`、`docs/方案解读卡.md`、`docs/接口契约.md`、`docs/用户手册.md`、`docs/数据字典.md`、`docs/阶段报告-M1.md`、`DECISIONS.md`、`PLAN-MATRIX.md`
- 证据：`docs/screenshots/`（20 张界面截图 + 权限隔离图）、`.runtime/artifacts/`（门禁日志、E2E 报告）

## 指标现状

- 短期预测 MAPE 均值：4.22%（回测加权组合）、5.92%（季节分解）、6.26%（Holt-Winters）、12.41%（梯度提升回归）→ 达成方案「≤12%～15%」
- 方向准确率均值：49.09%（7 日累计口径）→ 未达方案 65%，已在阶段报告「已知限制」如实披露并给出后续路径
- 接口响应：驾驶舱 40~90 ms、价格分页 30~60 ms、14 天预测 0.9~2.4 s

## 下一步

1. 按评审意见补充外生变量与更强模型，提升方向准确率（14/30 日累计口径目标 ≥60%）
2. 接入真实数据源适配器与增量同步（当前为 CSV 导入 + 种子数据）
3. 生产化改造：PostgreSQL/TimescaleDB、Redis、对象存储、容器部署与等保二级要求
4. 预警通知外发与处置工单流转
5. 若需中期预测（1~3 个月）与漂移监控，按 `PLAN-MATRIX.md` 的暂缓项触发条件启动
