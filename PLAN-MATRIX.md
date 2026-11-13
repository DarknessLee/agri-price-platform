# 方案—实现追踪矩阵（PLAN-MATRIX）

> 状态只用四种：`已实现` / `部分`（写清差什么）/ `暂缓`（写触发条件）/ `不做`（写理由）。
> 依据《农产品价格预测分析系统开发书（草案）》章节。证据列指向可复核的位置：接口门禁用例（`npm run test:api`）、端到端用例（`npm run test:e2e`）、截图（`docs/screenshots/`）、实现文件。
> 最近核对：M3（2026-11-13），五道门禁全 PASS（327 项断言），详见 `docs/阶段报告-M3.md`。

| 能力/交付项 | 方案出处 | 状态 | 证据（用例/文档/截图） | 备注 |
| --- | --- | --- | --- | --- |
| 数据采集：公开 API / 授权接口接入 | §4.1 | 部分 | `backend/app/services/ingest.py`、`/api/sources/\{id\}/sync` | 已留同步接口与数据源登记；真实三方 API 需授权后接适配器 |
| 数据采集：文件导入（CSV） | §4.1 | 已实现 | test:api「CSV 导入」用例、`frontend/src/views/data/ImportData.vue`、截图 13 | 模板下载、错误行回显、重复行幂等跳过 |
| 数据采集：人工填报 | §4.1 | 部分 | `dim_data_source` 类型含「人工填报」 | 填报合并入导入流程，暂无独立填报表单 |
| 数据校验：单位/编码/重复/缺失/异常 | §4.1 | 已实现 | `/api/quality/*`、`services/quality.py`、db:validate 质量标记校验、截图 12 | 四类问题：价格异常波动/缺失/重复/格式错误 |
| 数据治理：统一品种/地区/单位/频率口径 | §4.2 | 已实现 | `/api/admin/varieties`、`/api/admin/regions`、`/api/meta/dicts`、截图 16 | 主数据统一编码与单位 |
| 数据治理：血缘与版本 | §4.2 | 部分 | 导入任务记录、`audit_log` | 任务级可追溯；字段级血缘暂缓 |
| 数据仓库：价格事实表/特征表/预测表/预警表 | §4.2 | 已实现 | `backend/app/models.py`（24 表）、db:validate 表结构断言、`deploy/docker-compose.yml` | MySQL 8（`agri_price`）实现，可切回 SQLite；时序库 TimescaleDB 暂缓 |
| 监测：多市场对比（批发/零售） | §4.3 | 已实现 | `/api/prices`、`frontend/src/views/monitor/PriceMonitor.vue`、截图 02 | 12 个市场、2 种市场类型 |
| 监测：同比环比、季节指数、波动率、价差、比价 | §4.3 | 已实现 | `/api/prices/seasonality`、`/region-spread`、`/variety-compare`、截图 03 | 四项指标口径见用户手册 §4 |
| 监测：成本收益、供需景气指数 | §4.3 | 部分 | `feature_record.cost_index/freight_index/weather_score` | 以特征指标呈现，未做收益核算报表 |
| 监测：PC/大屏/响应式 | §4.3 | 已实现 | `layouts/MainLayout.vue`、驾驶舱与 19 页面、`views/Screen.vue` 数据大屏、截图 01~21 | 大屏为独立整屏（30 秒刷新）；1680×1050 与 1440 宽自适应，移动端未专项适配 |
| 预测：短期 7～30 天 | §4.4 | 已实现 | test:api 预测段（14 点区间/方向/解释）、截图 04 | horizon 支持 1~60，默认 14 |
| 预测：中期 1～3 个月 | §4.4 | 暂缓 | — | 触发条件：需要月度经营决策支持时扩展 horizon 与月度模型 |
| 预测：点/区间/置信度/方向 | §4.4 | 已实现 | `/api/forecast/run` 返回结构、截图 04 | 区间按回测残差分位数生成 |
| 预测：季节分解 / Holt-Winters / 组合 | §4.4 | 已实现 | `services/forecasting.py`、120 个模型版本、截图 06 | MAPE 均值 5.92% / 6.26% / 4.22% |
| 预测：ARIMA / Prophet | §4.4 | 部分 | `statsmodels` 依赖已装 | 未默认启用：与本数据季节性相比提升有限，可扩展为候选算法 |
| 预测：LightGBM / XGBoost / 随机森林 | §4.4 | 部分 | `services/forecasting.py` 梯度提升回归（sklearn） | 效果弱于组合模型（MAPE 12.41%），保留为特征验证基线 |
| 预测：深度学习（LSTM 等） | §4.4 | 不做 | — | 数据规模与算力不匹配，可解释性差 |
| 特征工程：同比/环比/季节/节假日/气象/成本/运费/期货/替代品 | §4.4 | 已实现 | `services/features.py`、`feature_record` 9 个特征列、31,380 行 | 气象/期货为指数化特征，接入实测值后可提升 |
| 预测：批量预测 | §6 | 已实现 | `/api/forecast/batch`（后台线程 + 进度）、`scripts/perf-batch.mjs`、test:api 批量异步段、截图 05 | 异步执行、进度可见；压测 1,800 点 4.27 s，外推 1 万点 ≈ 23.7 s（目标 ≤600 s） |
| 模型管理：训练/回测/版本/启用 | §4.4 | 已实现 | `/api/models/*`、`/api/models/\{id\}/backtest`、截图 06 | 每组合 4 算法、30 个在用版本 |
| 模型管理：灰度/漂移监控/定期重训 | §4.4 | 已实现 | `/api/models/drift`（PSI 90/180 天）、`services/governance.py`、`views/forecast/ModelDrift.vue`、截图 06b、test:api 漂移段 | 漂移等级 4 平稳 / 18 关注 / 8 漂移；灰度发布按比例分流暂缓（单机无流量调度需求） |
| 可解释性：特征贡献/预测依据 | §4.4 | 已实现 | `forecast_result.explain`、预测页因素条形图与结论卡 | 相对贡献度，非因果解释 |
| 预警：阈值/波动率/同比/价差规则 | §4.5 | 已实现 | `/api/alerts/rules`、`services/alerting.py`、截图 08 | 4 类规则 × 5 种比较符 |
| 预警：等级/通知/处置/闭环 | §4.5 | 已实现 | `/api/alerts/\{id\}/ack|close`、`/api/alerts/sla`、通知中心（`sys_notification`）、test:api 预警与 SLA 段、截图 07 | 状态流转 待处理→处理中→已关闭；站内通知覆盖 7 条链路；处置 SLA 默认 24 小时 |
| 预警：模型预警（残差/供需缺口） | §4.5 | 部分 | 预测偏差指标、情景推演 | 以情景推演与回测误差替代独立模型预警 |
| 情景推演：气象/运输/政策/替代品 | §4.6 | 已实现 | `/api/scenarios/*`、4 类模板、截图 09 | 冲击弹性系数模型，输出区间与建议 |
| 报告：日报/周报/月报 | §4.6 | 已实现 | `/api/reports/generate`、HTML/Markdown/Excel 下载、Excel 模板、test:api xlsx 段、截图 10 | 正文含价格概况、波动预警、预测摘要、建议；Excel 含概览/价格与预测/预警摘要三工作表 |
| 开放 API：价格/预测/预警/报告/指标 | §5.3 | 已实现 | `/api/open/v1/*`（5 个端点）、`X-Api-Key` 鉴权、429 限流（`E4290`）、调用方管理与调用统计（`/api/open-clients/*`）、test:api 密钥限流段、截图 19 | 支持调用方密钥、每分钟限流、7 天调用流水（耗时/错误率/Top 路径） |
| 交互：站内通知中心 | §4.5 | 已实现 | `sys_notification`、`/api/notifications/*`、`components/NotificationBell.vue`、test:api 通知段 | 7 条产生链路；未接外部短信/邮件通道 |
| 后台：用户/角色/机构/菜单/审计 | §4.7 | 已实现 | `/api/users`、`/api/roles`、`/api/audit-logs`、截图 14/15/17 | 机构为字段级，菜单按权限动态过滤 |
| 后台：数据源/品种/地区/指标/规则配置 | §4.7 | 已实现 | `/api/sources`、`/api/admin/*`、截图 11/16 | 市场主数据只读 |
| 后台：任务调度/系统监控 | §4.7 | 已实现 | `backend/app/scheduler.py`（5 段 cron + 守护线程）、`services/tasks.py`（真实执行 + 失败重试）、`/api/tasks/runs`、`/api/tasks/tick`、`views/admin/Monitor.vue`、截图 18/22、test:api 调度与监控段 | 5 个任务到点自动触发、运行史可查；监控含接口指标、日志检索、服务状态与测试邮件；外部告警渠道未接入 |
| 非功能：查询 ≤3 秒 | §6 | 已实现 | test:api 全量 212 断言 22 s；驾驶舱 40~90 ms（缓存命中 <10 ms）；漂移接口缓存命中 0.059 s；对象存储读取 12~30 ms | 本机 MySQL 8 + Redis 7 + MinIO，数据量 8 万级 |
| 非功能：批量预测 1 万条 ≤10 分钟 | §6 | 已实现 | `scripts/perf-batch.mjs`：1,800 点 4.27 s → 421 点/秒，外推 1 万点 ≈ 23.7 s | 后台线程异步执行；若需严格实测 1 万点，可调大组合数与 horizon 后复跑脚本 |
| 非功能：可用性 99.5% | §6 | 部分 | 单机部署说明、`.runtime/logs/` | 无多副本与故障转移 |
| 安全：认证/RBAC/审计/脱敏 | §6 | 已实现 | `security.py`、test:api 权限隔离段（4 角色）、截图 20 | 口令 PBKDF2、token 8 小时；敏感字段不落日志 |
| 安全：传输加密与等保二级 | §2.2 | 部分 | 部署层可选 HTTPS | 未做等保测评与渗透测试 |
| 中间件：Redis 热点缓存与令牌黑名单 | §5.1 | 已实现 | `backend/app/cache.py`、`X-Cache: HIT/MISS` 响应头、注销后旧 token 失效用例 | 驾驶舱/字典/性能接口缓存 30~300 s；不可用时自动降级直连 |
| 中间件：对象存储（MinIO/S3） | §5.1 | 已实现 | `backend/app/storage.py`、桶 `agri-artifacts`、报告正文/模型产物/导入文件对象键、`/api/storage/health`、`scripts/backup.mjs` 对象清单 | MinIO 不可达时自动降级本地 FS（同一对象键）；Kafka/MLflow/ELK/Prometheus/K8s 以等价实现替代，见下三行 |
| 中间件：调度（替代 Airflow） | §5.1 | 已实现 | `backend/app/scheduler.py`、`services/tasks.py`、`scheduled_task_run`、`/api/tasks/tick` | 进程内守护线程 + 数据库运行史；多实例需租约锁（已知限制） |
| 中间件：可观测性（替代 ELK/Prometheus） | §5.1 | 已实现 | `backend/app/logging_setup.py`（JSONL + request_id）、`services/metrics.py`（分钟桶）、`/api/logs`、`/api/metrics/*`、`/api/system/status`、截图 22 | 指标驻留内存（重启归零）、日志尾部检索；未接外部告警 |
| 中间件：实验跟踪（替代 MLflow） | §5.1 | 已实现 | `model_run` 表、`services/experiments.py`、`/api/models/runs`、`/api/models/retrain-drifted`、`views/forecast/ModelManage.vue` 实验记录 | 记录算法/超参/指标/耗时/产物键；无 run 级 UI 对比矩阵 |
| 中间件：Kafka/K8s/TimescaleDB | §5.1 | 暂缓 | `DECISIONS.md` D05/D15/D22/D23 | 触发条件：生产化部署、多实例并发与亿级时序数据；当前用后台线程 + compose + MySQL 聚合替代 |
| 交付：一键启动/种子重建/备份/门禁/文档/截图 | §12 | 已实现 | `npm run dev`、`npm run seed`、`npm run backup`、`npm run gate`（五门禁 327 项断言）、14 份文档、24 张截图 | 见 `docs/阶段报告-M3.md` |
| 软著登记材料（60 页源码+手册+申请表） | 案例复盘 §17.8 | 不做 | — | 默认不做；如需要另行立项 |
