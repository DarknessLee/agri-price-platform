# 农产品价格监测预测分析平台

面向农业主管部门、批发市场、合作社与金融机构的价格监测、短期预测、预警处置与决策支持平台。系统围绕「采集—治理—监测—预测—预警—决策支持」闭环，提供驾驶舱、价格监测分析、短期与批量预测、模型管理、预警规则与处置、情景推演、分析报告、数据治理、后台管理与开放 API 十一个业务模块。

- 前端：Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia
- 后端：FastAPI + SQLAlchemy + MySQL 8.0 + Redis 7 + pandas / NumPy / scikit-learn / statsmodels
- 部署形态：单机 B/S，前后端分离，生产构建由后端统一托管静态资源
- 数据服务：MySQL 承担业务数据存储（可切回内置 SQLite 文件库），Redis 承担热点缓存与令牌注销黑名单，两者均支持不可用时降级
- 鉴权：HS256 JWT + PBKDF2 口令散列 + RBAC 权限点（21 个权限点、4 个内置角色）

## 环境要求

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python 3.11 ~ 3.13 | 3.12 | 项目在 Python 3.12 下开发验证，依赖见 `backend/requirements.txt` |
| Node.js 20 LTS 及以上 | 20 ~ 24 | 项目在 Node 24 下验证 |
| Docker（含 Compose 插件） | 20.10+ | 用于运行 MySQL 与 Redis；本机已有同名容器时可直接复用 |
| MySQL | 8.0 | 容器 `127.0.0.1:13306`，库 `agri_price`，账号 `agri / Agri_2026` |
| Redis | 7.x | 容器 `127.0.0.1:16379`，密码 `DataSec_2026`，库 0 |
| 浏览器 | Chromium 内核 120+ | 界面面向 1600×1000 及以上分辨率 |

数据服务连接参数集中在 `backend/app/config.py`，也可用环境变量覆盖（`AGRI_DATABASE_URL`、`AGRI_REDIS_URL`、`AGRI_DB_BACKEND`）；设置 `AGRI_DB_BACKEND=sqlite` 时退化为 `.runtime/agri.db` 单文件库，无需 Docker 即可运行。

前端与后端端口固定：

- 后端 API：`http://127.0.0.1:8017`
- 前端开发服务：`http://127.0.0.1:5177`（`/api` 反向代理到 8017）

## 目录结构

```
agri-price-platform/
├─ backend/app/            后端应用（routers 接口 / services 业务 / models 数据模型 / seed 种子）
├─ frontend/src/           前端源码（views 页面 / components 公共组件 / api 请求层 / stores 状态）
├─ docs/                   方案解读卡、接口契约、阶段报告、用户手册、数据字典、截图
├─ e2e/                    Playwright 端到端用例
├─ scripts/                构建、种子、接口、数据库、文档、截图与总门禁脚本
├─ STATUS.md               当前阶段与下一步
├─ DECISIONS.md            技术决策记录（D01–D11）
├─ PLAN-MATRIX.md          方案条款 → 实现 → 证据 矩阵
└─ .runtime/               运行期数据库、日志与过程产物（不纳入版本库）
```

## 快速开始

```bash
# 1) 启动并检查数据服务（MySQL 13306 + Redis 16379；复用本机已有容器，缺失时提示用 compose 拉起）
npm run infra:up

# 2) 安装依赖
python -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.txt
npm install
npm install --prefix frontend

# 3) 构建前端并生成种子数据（首次建库会自动创建 3 年日频价格数据与 30 个在用模型）
npm run seed

# 4) 开发模式（后端 8017 + 前端 5177 同时启动）
npm run dev

# 5) 生产构建与整体验收
npm run build
npm run gate
```

`npm run seed` 会重建 MySQL 库 `agri_price` 中的业务数据（清空后重新导入）：5 个品种 × 6 个地区 × 12 个市场 × 2023-01-01～2026-11-11 日频价格与特征、预警规则与预警记录、分析报告、数据源、导入任务、质量异常、调度任务与审计日志，并训练季节分解、Holt-Winters、梯度提升回归和回测加权组合模型，输出示例预测结果。种子使用固定随机种子，可重复重放；`npm run seed -- --no-models` 可跳过模型训练快速建库。

### 内置账号

| 账号 | 口令 | 角色 | 权限范围 |
| --- | --- | --- | --- |
| admin | Admin@2026 | 系统管理员 | 全部 21 个权限点 |
| analyst01 | Analyst@2026 | 分析师 | 监测、预测、模型、预警查看、情景、报告 |
| operator01 | Operator@2026 | 运营人员 | 监测、预警处置与规则、报告查看、数据导入 |
| viewer01 | Viewer@2026 | 只读用户 | 驾驶舱、监测、预测、预警、报告查看 |

登录后按角色动态生成菜单与按钮权限，越权访问由后端返回 `E4030` 并在前端跳转至无权限页。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `npm run infra:up` | 检查并启动 MySQL/Redis，幂等准备业务库、账号与连通性 |
| `npm run infra:down` | 停止由 `deploy/docker-compose.yml` 启动的数据服务 |
| `npm run dev` | 同时启动后端 8017 与前端 5177 |
| `npm run build` | 前端类型检查 + 生产构建，产物输出到 `frontend/dist` |
| `npm run seed` | 重建种子数据库（`--reset` 清空业务数据） |
| `npm run test:api` | 启动后端并执行接口契约与权限隔离断言 |
| `npm run test:e2e` | 使用 Playwright 执行端到端用例（需先 `npm run build`） |
| `npm run db:validate` | 校验数据库表结构、数据规模、引用完整性与取值合法性 |
| `npm run check:docs` | 校验交付文档、截图与页面完整性 |
| `npm run screenshots` | 生成 `docs/screenshots` 全套页面截图 |
| `npm run gate` | 依次执行构建、数据库、接口、端到端、文档五道门禁 |

每道门禁最后一行固定输出：

```
RESULT=PASS passed=N failed=M 用时=Ss
```

`npm run gate` 汇总五道门禁结果，任一失败即视为交付不合格。

## 接口约定

- 统一响应：`{"code": "0", "message": "ok", "data": ...}`；分页数据为 `{"list": [], "total": 0, "page": 1, "page_size": 20}`
- 错误码：`E4001` 参数校验失败、`E4002` 参数格式错误、`E4010` 未认证/凭证失效、`E4030` 无权限、`E4040` 资源不存在、`E4090` 状态冲突、`E5000` 服务内部错误
- 鉴权：除 `POST /api/auth/login` 与 `GET /api/health` 外均需 `Authorization: Bearer <token>`
- 完整端点表、字段说明与角色权限映射见 `docs/接口契约.md`
- 开放 API 位于 `/api/open/v1/*`，供第三方系统以同一套凭证读取价格、预测、预警、报告与运行指标

## 数据与指标口径

- 价格单位统一为「元/公斤」，日期粒度日频
- 短期预测 MAPE 目标 ≤ 15%，方向准确率目标 ≥ 65%（主口径为 30 日趋势累计方向命中率；接口同时返回 7 日/单日参考口径与说明字段）
- 驾驶舱与监测页的同比、环比、季节指数、区域价差、品种比价指数均以数据库实时聚合，不使用硬编码常量
- 种子数据由固定随机种子生成，重建后指标可复现，便于对照验收

## 常见问题

1. **构建时报 `esbuild ... Access is denied`**：本机系统临时目录清理受限，`npm run build` 已自动将 `TMP/TEMP` 指向 `frontend/.tmp`；手工执行时同样建议设置该环境变量。
2. **控制台中文乱码**：Windows 控制台默认 GBK，执行脚本时设置 `PYTHONIOENCODING=utf-8`（门禁脚本已内置）。
3. **数据服务未就绪**：执行 `npm run infra:up`；若提示容器不存在，用 `docker compose -f deploy/docker-compose.yml up -d` 启动并等待健康检查通过。
4. **MySQL 连接被拒或库为空**：确认容器映射端口为 13306、库名为 `agri_price`；`npm run seed` 后可用 `npm run db:validate` 校验数据规模。
5. **Redis 不可用**：接口会自动降级为直连数据库（健康检查 `cache` 字段显示 `error`），页面功能不受影响；恢复 Redis 后缓存自动重新填充。
6. **数据库被占用**：停止占用 8017 端口的进程后重试 `npm run seed`；`.runtime/` 下的日志与导入产物可安全删除。
7. **首次启动较慢**：首次种子需要训练 30 个模型（约 2 分钟），之后启动直接读取已有数据。

## 交付文档索引

| 文档 | 内容 |
| --- | --- |
| `STATUS.md` | 当前阶段、已完成项、风险与下一步 |
| `DECISIONS.md` | 技术选型与关键取舍（D01–D15，含存储与缓存升级记录） |
| `PLAN-MATRIX.md` | 方案条款到实现与证据的映射矩阵 |
| `docs/接口契约.md` | 接口、字段、错误码、角色权限、前端路由 |
| `docs/方案解读卡.md` | 方案定位、核心闭环、技术栈可替换性、分期计划 |
| `docs/用户手册.md` | 各角色操作路径与业务说明 |
| `docs/数据字典.md` | 数据表、字段、枚举与计算口径 |
| `docs/阶段报告-M1.md` | 本阶段目标、交付、门禁结果与遗留 |
