"""预警管理路由（契约 §7）：预警列表、统计、处置、规则扫描与规则 CRUD。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .. import cache
from ..database import get_db
from ..models import Region, Variety
from ..responses import ok, paged, page_args
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services import alerting

router = APIRouter(tags=["预警管理"])

ALERT_EXPORT_HEADER = ["级别", "标题", "品种", "地区", "预警日期", "状态", "规则", "详情", "处理人", "处理时间"]


def _body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("E4001", "请求体格式不正确", 400)
    return body


def _csv_response(rows: list[list[Any]], filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _rule_payload(db: Session, rule: Any) -> dict:
    variety = db.get(Variety, int(rule.variety_id)) if rule.variety_id else None
    region = db.get(Region, int(rule.region_id)) if rule.region_id else None
    return alerting.serialize_rule(
        rule,
        variety.name if variety else "",
        region.name if region else "",
    )


@router.get("/alerts")
def alerts_list(
    status: str | None = Query(default=None),
    level: str | None = Query(default=None),
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    user: Any = Depends(require_permission("alert:view")),
    db: Session = Depends(get_db),
):
    """预警记录分页列表。"""
    page, page_size = page_args(page, page_size)
    items, total = alerting.list_alerts(db, status, level, variety_id, region_id, page, page_size)
    return paged(items, total, page, page_size)


@router.get("/alerts/statistics")
def alerts_statistics(
    user: Any = Depends(require_permission("alert:view")),
    db: Session = Depends(get_db),
):
    """预警统计：未处置数、近 30 天总量、级别/状态分布、近 14 天趋势与处置率。"""
    return ok(alerting.stats(db))


@router.get("/alerts/export")
def alerts_export(
    status: str | None = Query(default=None),
    level: str | None = Query(default=None),
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    user: Any = Depends(require_permission("alert:view")),
    db: Session = Depends(get_db),
):
    """导出预警记录 CSV。"""
    rows: list[list[Any]] = [ALERT_EXPORT_HEADER]
    page = 1
    collected = 0
    while collected < 5000:
        items, total = alerting.list_alerts(db, status, level, variety_id, region_id, page, 100)
        if not items:
            break
        for item in items:
            rows.append(
                [
                    item["level"],
                    item["title"],
                    item["variety"],
                    item["region"],
                    item["alert_date"],
                    item["status"],
                    item["rule_name"],
                    item["detail"],
                    item["handler"],
                    item["handled_at"],
                ]
            )
        collected += len(items)
        if collected >= total:
            break
        page += 1
    return _csv_response(rows, "alerts.csv")


@router.post("/alerts/evaluate")
def alerts_evaluate(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("alert:rule")),
    db: Session = Depends(get_db),
):
    """扫描规则并生成预警记录。"""
    data = _body_dict(body)
    try:
        days = int(data.get("days", 30) or 30)
    except (TypeError, ValueError):
        raise ApiError("E4001", "扫描天数必须为整数", 400)
    result = alerting.evaluate_rules(db, days=days)
    cache.invalidate("dashboard")
    write_audit(
        db,
        user,
        "执行预警扫描",
        "预警管理",
        f"扫描天数={days} 新增={result.get('created')} 命中={result.get('scanned')}",
        client_ip(request),
    )
    return ok(result)


@router.get("/alerts/rules")
def alerts_rules_list(
    user: Any = Depends(require_permission("alert:view")),
    db: Session = Depends(get_db),
):
    """预警规则列表。"""
    return ok(alerting.list_rules(db))


@router.post("/alerts/rules")
def alerts_rules_create(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("alert:rule")),
    db: Session = Depends(get_db),
):
    """新建预警规则。"""
    rule = alerting.create_rule(db, _body_dict(body), user)
    write_audit(db, user, "新增预警规则", "预警管理", f"规则ID={rule.id} 名称={rule.name}", client_ip(request))
    return ok(_rule_payload(db, rule))


@router.put("/alerts/rules/{rule_id}")
def alerts_rules_update(
    rule_id: int,
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("alert:rule")),
    db: Session = Depends(get_db),
):
    """修改预警规则。"""
    rule = alerting.update_rule(db, rule_id, _body_dict(body))
    write_audit(db, user, "修改预警规则", "预警管理", f"规则ID={rule.id} 名称={rule.name}", client_ip(request))
    return ok(_rule_payload(db, rule))


@router.delete("/alerts/rules/{rule_id}")
def alerts_rules_delete(
    rule_id: int,
    request: Request,
    user: Any = Depends(require_permission("alert:rule")),
    db: Session = Depends(get_db),
):
    """删除预警规则（已产生预警记录的规则不可删除）。"""
    alerting.delete_rule(db, rule_id)
    write_audit(db, user, "删除预警规则", "预警管理", f"规则ID={rule_id}", client_ip(request))
    return ok({"id": rule_id})


@router.post("/alerts/rules/{rule_id}/toggle")
def alerts_rules_toggle(
    rule_id: int,
    request: Request,
    user: Any = Depends(require_permission("alert:rule")),
    db: Session = Depends(get_db),
):
    """启用 / 停用预警规则。"""
    result = alerting.toggle_rule(db, rule_id)
    write_audit(
        db,
        user,
        "切换预警规则状态",
        "预警管理",
        f"规则ID={rule_id} 启用={result.get('enabled')}",
        client_ip(request),
    )
    return ok(result)


@router.post("/alerts/{alert_id}/ack")
def alerts_ack(
    alert_id: int,
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("alert:handle")),
    db: Session = Depends(get_db),
):
    """确认预警（状态转为处理中）。"""
    data = _body_dict(body)
    result = alerting.ack_alert(db, alert_id, user, note=str(data.get("note") or ""))
    write_audit(db, user, "确认预警", "预警管理", f"预警ID={alert_id}", client_ip(request))
    return ok(result)


@router.post("/alerts/{alert_id}/close")
def alerts_close(
    alert_id: int,
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("alert:handle")),
    db: Session = Depends(get_db),
):
    """关闭预警（填写处置意见）。"""
    data = _body_dict(body)
    result = alerting.close_alert(
        db,
        alert_id,
        user,
        note=str(data.get("note") or ""),
        result=str(data.get("result") or ""),
    )
    write_audit(db, user, "关闭预警", "预警管理", f"预警ID={alert_id}", client_ip(request))
    return ok(result)


@router.get("/alerts/{alert_id}")
def alerts_detail(
    alert_id: int,
    user: Any = Depends(require_permission("alert:view")),
    db: Session = Depends(get_db),
):
    """预警详情。"""
    return ok(alerting.alert_detail(db, alert_id))
