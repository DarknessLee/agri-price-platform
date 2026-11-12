"""数据库校验门禁（MySQL / SQLite 通用）。

直接使用 ``app.config.DATABASE_URL`` 通过 SQLAlchemy 连接数据库，执行 34 项
结构与业务数据检查，把结果以单行 JSON 输出到 stdout，由
``scripts/db-validate.mjs`` 负责渲染 [PASS]/[FAIL] 与 RESULT 行。

JSON 结构::

    {"dialect": "mysql", "counts": {...},
     "checks": [{"name": "...", "ok": true, "detail": "..."}, ...]}

退出码：全部通过 0，否则 1（连接失败同样为 1）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import DATABASE_URL  # noqa: E402


class Checks:
    """轻量断言收集器，行为与 scripts/lib.mjs 的 Checker 保持一致。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})

    def equal(self, name: str, actual, expected) -> None:
        self.check(
            name,
            actual == expected,
            f"期望 {json.dumps(expected, ensure_ascii=False)} 实际 {json.dumps(actual, ensure_ascii=False)}",
        )

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.items)


EXPECTED_TABLES = [
    "sys_role",
    "sys_permission",
    "sys_role_permission",
    "sys_menu",
    "sys_user",
    "dim_variety",
    "dim_region",
    "dim_market",
    "dim_data_source",
    "price_record",
    "feature_record",
    "model_version",
    "forecast_result",
    "forecast_batch",
    "forecast_batch_item",
    "backtest_record",
    "alert_rule",
    "alert_record",
    "scenario_sim",
    "report",
    "import_task",
    "quality_issue",
    "scheduled_task",
    "audit_log",
    "sys_notification",
    "open_api_client",
    "open_api_call",
]

COUNT_SQL = {
    "varieties": "SELECT COUNT(*) FROM dim_variety",
    "regions": "SELECT COUNT(*) FROM dim_region",
    "markets": "SELECT COUNT(*) FROM dim_market",
    "users": "SELECT COUNT(*) FROM sys_user",
    "permissions": "SELECT COUNT(*) FROM sys_permission",
    "rolePermissions": "SELECT COUNT(*) FROM sys_role_permission",
    "menus": "SELECT COUNT(*) FROM sys_menu",
    "prices": "SELECT COUNT(*) FROM price_record",
    "features": "SELECT COUNT(*) FROM feature_record",
    "alerts": "SELECT COUNT(*) FROM alert_record",
    "rules": "SELECT COUNT(*) FROM alert_rule",
    "reports": "SELECT COUNT(*) FROM report",
    "models": "SELECT COUNT(*) FROM model_version",
    "forecasts": "SELECT COUNT(*) FROM forecast_result",
    "scenarios": "SELECT COUNT(*) FROM scenario_sim",
    "qualityIssues": "SELECT COUNT(*) FROM quality_issue",
    "importTasks": "SELECT COUNT(*) FROM import_task",
    "tasks": "SELECT COUNT(*) FROM scheduled_task",
    "audits": "SELECT COUNT(*) FROM audit_log",
    "sources": "SELECT COUNT(*) FROM dim_data_source",
    "notifications": "SELECT COUNT(*) FROM sys_notification",
    "apiClients": "SELECT COUNT(*) FROM open_api_client",
    "apiCalls": "SELECT COUNT(*) FROM open_api_call",
}


def run_checks(engine) -> tuple[dict, list[dict]]:
    checks = Checks()
    counts: dict[str, int] = {}

    with engine.connect() as conn:
        def scalar(sql: str):
            return conn.execute(text(sql)).scalar()

        table_names = set(inspect(conn).get_table_names())
        missing = [name for name in EXPECTED_TABLES if name not in table_names]
        checks.check("核心数据表齐全（27 张）", not missing, f"缺少：{', '.join(missing)}")

        for key, sql in COUNT_SQL.items():
            counts[key] = int(scalar(sql) or 0)

        # ---------------------------------------------------------- 数据量
        checks.equal("品种数量 = 5", counts["varieties"], 5)
        checks.equal("地区数量 = 6", counts["regions"], 6)
        checks.equal("市场数量 = 12", counts["markets"], 12)
        checks.equal("用户数量 = 7", counts["users"], 7)
        checks.equal("权限点数量 = 21", counts["permissions"], 21)
        checks.check("角色权限关联 >= 40", counts["rolePermissions"] >= 40, f"实际 {counts['rolePermissions']}")
        checks.check("菜单数量 >= 15", counts["menus"] >= 15, f"实际 {counts['menus']}")
        checks.check("价格记录 >= 80000", counts["prices"] >= 80000, f"实际 {counts['prices']}")
        checks.check("特征记录 >= 30000", counts["features"] >= 30000, f"实际 {counts['features']}")
        checks.check("预警记录 >= 6", counts["alerts"] >= 6, f"实际 {counts['alerts']}")
        checks.check("预警规则 >= 6", counts["rules"] >= 6, f"实际 {counts['rules']}")
        checks.check("分析报告 >= 3", counts["reports"] >= 3, f"实际 {counts['reports']}")
        checks.check("调度任务 = 5", counts["tasks"] == 5, f"实际 {counts['tasks']}")
        checks.check("数据源 >= 4", counts["sources"] >= 4, f"实际 {counts['sources']}")
        checks.check("质量异常 >= 20", counts["qualityIssues"] >= 20, f"实际 {counts['qualityIssues']}")
        checks.check("导入任务 >= 3", counts["importTasks"] >= 3, f"实际 {counts['importTasks']}")
        checks.check("审计日志 >= 18", counts["audits"] >= 18, f"实际 {counts['audits']}")
        checks.check("模型版本 >= 4（已完成训练）", counts["models"] >= 4, f"实际 {counts['models']}")
        checks.check("预测结果记录 >= 5", counts["forecasts"] >= 5, f"实际 {counts['forecasts']}")
        checks.check("站内通知 >= 10", counts["notifications"] >= 10, f"实际 {counts['notifications']}")
        checks.equal("开放 API 调用方 = 3", counts["apiClients"], 3)
        checks.check("开放 API 调用流水 >= 200", counts["apiCalls"] >= 200, f"实际 {counts['apiCalls']}")

        # ---------------------------------------------------------- 时间范围
        min_date = scalar("SELECT MIN(price_date) FROM price_record")
        max_date = scalar("SELECT MAX(price_date) FROM price_record")
        min_text = str(min_date) if min_date is not None else "None"
        max_text = str(max_date) if max_date is not None else "None"
        checks.check("价格数据起始日期 <= 2023-01-01", min_text <= "2023-01-01", f"实际 {min_text}")
        checks.check("价格数据最新日期 >= 2026-11-11", max_text >= "2026-11-11", f"实际 {max_text}")

        # ---------------------------------------------------------- 唯一性
        dup_price = scalar(
            """SELECT COUNT(*) FROM (
                 SELECT variety_id, market_id, price_date, market_type, COUNT(*) AS c
                 FROM price_record
                 GROUP BY variety_id, market_id, price_date, market_type
                 HAVING COUNT(*) > 1
               ) AS dup"""
        )
        checks.equal("价格记录无重复点", int(dup_price or 0), 0)

        # ---------------------------------------------------------- 引用完整性
        orphan_prices = scalar(
            """SELECT COUNT(*) FROM price_record p
               LEFT JOIN dim_variety v ON v.id = p.variety_id
               LEFT JOIN dim_region r ON r.id = p.region_id
               LEFT JOIN dim_market m ON m.id = p.market_id
               WHERE v.id IS NULL OR r.id IS NULL OR m.id IS NULL"""
        )
        checks.equal("价格记录品种/地区/市场引用完整", int(orphan_prices or 0), 0)

        orphan_features = scalar(
            """SELECT COUNT(*) FROM feature_record f
               LEFT JOIN dim_variety v ON v.id = f.variety_id
               LEFT JOIN dim_region r ON r.id = f.region_id
               WHERE v.id IS NULL OR r.id IS NULL"""
        )
        checks.equal("特征记录引用完整", int(orphan_features or 0), 0)

        orphan_alerts = scalar(
            """SELECT COUNT(*) FROM alert_record a
               LEFT JOIN alert_rule ru ON ru.id = a.rule_id
               WHERE ru.id IS NULL"""
        )
        checks.equal("预警记录均关联有效规则", int(orphan_alerts or 0), 0)

        orphan_forecast = scalar(
            """SELECT COUNT(*) FROM forecast_result f
               LEFT JOIN model_version m ON m.id = f.model_id
               WHERE m.id IS NULL"""
        )
        checks.equal("预测结果均关联模型版本", int(orphan_forecast or 0), 0)

        # ---------------------------------------------------------- 业务合理性
        bad_price = scalar("SELECT COUNT(*) FROM price_record WHERE price <= 0 OR price IS NULL")
        checks.equal("价格均大于 0", int(bad_price or 0), 0)

        bad_quality = scalar(
            """SELECT COUNT(*) FROM price_record
               WHERE quality_flag NOT IN ('正常', '缺失', '异常', '重复', '疑似异常', '缺失估算')"""
        )
        checks.equal("质量标记取值合法", int(bad_quality or 0), 0)

        bad_status = scalar(
            """SELECT COUNT(*) FROM alert_record
               WHERE status NOT IN ('待处理', '处理中', '已关闭')"""
        )
        checks.equal("预警状态取值合法", int(bad_status or 0), 0)

        active_models = int(scalar("SELECT COUNT(*) FROM model_version WHERE is_active = 1") or 0)
        checks.check("存在启用中的模型", active_models >= 1, f"实际 {active_models}")

        admin_user = int(
            scalar("SELECT COUNT(*) FROM sys_user WHERE username = 'admin' AND status = '启用'") or 0
        )
        checks.equal("管理员账号存在且启用", admin_user, 1)

        admin_perms = int(
            scalar("SELECT COUNT(*) FROM sys_role_permission rp WHERE rp.role_key = 'admin'") or 0
        )
        checks.check("admin 角色拥有全部权限点（21）", admin_perms >= 21, f"实际 {admin_perms}")

        viewer_perms = int(
            scalar(
                """SELECT COUNT(*) FROM sys_role_permission rp
                   WHERE rp.role_key = 'viewer' AND rp.perm_key LIKE 'admin:%'"""
            )
            or 0
        )
        checks.equal("观察员不含后台管理权限", viewer_perms, 0)

    return counts, checks.items


def main() -> int:
    payload: dict = {"dialect": "unknown", "counts": {}, "checks": []}
    engine = None
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
        payload["dialect"] = engine.dialect.name
        counts, items = run_checks(engine)
        payload["counts"] = counts
        payload["checks"] = items
    except Exception as exc:  # 连接失败或查询异常：输出结构化失败项，便于门禁统一渲染
        payload["checks"] = payload["checks"] or []
        payload["checks"].append(
            {
                "name": "数据库可连接并完成校验",
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:500],
            }
        )
    finally:
        if engine is not None:
            engine.dispose()

    print(json.dumps(payload, ensure_ascii=False))
    return 0 if all(item["ok"] for item in payload["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
