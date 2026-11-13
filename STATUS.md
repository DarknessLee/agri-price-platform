# 当前状态（STATUS）

- 项目/版本：农产品价格预测分析系统 V1.0（`agri-price-platform`）
- 当前阶段：M3 完成（基础设施增强：调度与任务运行史、对象存储、可观测性与邮件通道、模型实验跟踪与备份；五道门禁 324 项通过）
- 最近更新：2026-11-13
- 当前分支：`master`（远端 `gitea` + `github`，`git pushall` 同时推送）
- 运行入口：`npm run infra:up`（MySQL 13306 / Redis 16379 / MinIO 9000-9001 / Mailpit 1025-8025 就绪检查）→ `npm run seed` → `npm run dev` → 前端 `http://127.0.0.1:5177`、后端 `http://127.0.0.1:8017`
- 数据重建：`npm run seed`（清空 MySQL 库 `agri_price` 并重建 84,660 条价格、31,380 条特征、120 个模型版本、19 条站内通知、10 条任务运行史、5 条邮件记录与开放 API 调用流水）
- 数据备份：`npm run backup`（mysqldump + 对象清单 + 关键表行数，保留最近 7 份于 `.runtime/backups/`）
- 技术栈：Vue 3 + TypeScript + ECharts 前端；FastAPI + SQLAlchemy + MySQL 8 后端；Redis 7 缓存、限流与令牌黑名单；MinIO（S3）对象存储；Mailpit 收件箱（均支持降级）；SQLite 作为无 Docker 环境的回退存储
- 内置账号：`admin/Admin@2026`、`analyst01/Analyst@2026`、`operator01/Operator@2026`、`viewer01/Viewer@2026`

## 最近验收

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 构建 | `npm run build` | `RESULT=PASS passed=12 failed=0 用时=16s` |
| 数据库 | `npm run db:validate` | `RESULT=PASS passed=40 failed=0 用时=1s` |
| 接口 | `npm run test:api` | `RESULT=PASS passed=212 failed=0 用时=22s` |
| 端到端 | `npm run test:e2e` | `RESULT=PASS passed=21 failed=0 用时=60s` |
| 文档 | `npm run check:docs` | `RESULT=PASS passed=39 failed=0 用时=0.0s` |
| 汇总 | `npm run gate` | `RESULT=PASS passed=324 failed=0 用时=92s` |

一键复跑：`npm run gate`（串行执行五道门禁，任一失败即停止并保留日志于 `.runtime/artifacts/`）。

## 交付物

- 代码：`backend/`（FastAPI，30 张表、14 路由模块、15 服务模块，MySQL 存储 + Redis 缓存/限流 + MinIO 对象存储 + 进程内调度器）、`frontend/`（Vue3 + TS，25 视图，含数据大屏与系统监控）、`scripts/`（门禁、压测、备份、启动与数据服务脚本）、`e2e/`（Playwright 用例）、`deploy/docker-compose.yml`（MySQL / Redis / MinIO / Mailpit 编排）
- 文档：`README.md`、`STATUS.md`、`DECISIONS.md`、`PLAN-MATRIX.md`、`docs/方案解读卡.md`、`docs/接口契约.md`、`docs/接口契约-M2.md`、`docs/接口契约-M3.md`、`docs/用户手册.md`、`docs/数据字典.md`（阶段验收报告为过程文档，已按手册清理且不纳入 git）
- 证据：`docs/screenshots/`（24 张界面截图，含数据大屏、模型监测、系统监控、权限隔离）、`.runtime/artifacts/`（门禁日志、E2E 报告）、`.runtime/backups/`（备份产物）

## 指标现状

- 短期预测 MAPE 均值：4.22%、区间 [1.54, 9.61]%（回测加权组合）、5.92%（季节分解）、6.26%（Holt-Winters）、12.41%（梯度提升回归）→ 达成方案「≤12%～15%」
- 方向准确率均值：77.89%、区间 [4.00, 100.00]%（主口径：30 日趋势累计方向命中率，7 日移动平均去噪）→ 达成方案 65%；7 日累计与单日参考口径分别为 52%~63% 与约 50%，接口已通过 `direction_acc_note`/`direction_acc_7d`/`direction_acc_1d` 如实披露
- 模型漂移（PSI 90/180 天）：30 个在用模型 4 平稳 / 18 关注 / 8 漂移，平均 PSI 0.2565
- 批量预测：提交 0.029 s 返回，30 组合 × 14 天约 2.16 s；压测 1,800 点 4.27 s，外推 1 万点约 23.7 s（目标 ≤600 s）
- 接口响应：驾驶舱 40~90 ms（缓存命中 <10 ms）、价格分页 30~60 ms、14 天预测 0.9~2.4 s、漂移接口缓存命中 0.059 s
- 预警处置：SLA 24 小时，站内通知 7 条链路（扫描/确认/关闭/导入/训练/报告/任务），高等级预警与任务失败同步发信（Mailpit 收件箱可查）
- 调度：5 条定时任务 cron 解析 + 到点触发 + 运行史（成功/失败/耗时），失败自动重试一次并通知
- 可观测性：接口日志（request_id/耗时/状态/缓存命中）与分钟指标（QPS、P50/P95/P99、错误率、慢请求 Top）可在系统监控页查看

## 下一步

1. 事件总线：Redis Streams 承载批量预测与通知，支持重试与死信队列（不引入 Kafka）
2. 指标持久化：分钟指标写入 MySQL 并保留 7 天，结合慢查询与阈值告警
3. 调度高可用：数据库租约锁 + 多实例抢占，避免重复触发
4. 生产化改造：PostgreSQL/TimescaleDB 时序扩展、容器化应用镜像、对象存储生命周期策略、等保二级要求（MySQL + Redis + MinIO + Mailpit 已在本机落地）
5. 接入真实数据源适配器与增量同步（当前为 CSV 导入 + 种子数据）
