"""情景推演路由（契约 §8）：模板、执行推演、历史记录与详情。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..responses import ok, paged, page_args
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services import scenario

router = APIRouter(tags=["情景推演"])


def _body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("E4001", "请求体格式不正确", 400)
    return body


def _as_int(value: Any, label: str, required: bool = True) -> int | None:
    if value in (None, ""):
        if required:
            raise ApiError("E4001", f"请填写{label}", 400)
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("E4001", f"{label}必须为整数", 400)


def _run(data: dict, request: Request, user: Any, db: Session) -> dict:
    variety_id = _as_int(data.get("variety_id"), "品种")
    region_id = _as_int(data.get("region_id"), "地区")
    horizon = _as_int(data.get("horizon"), "推演步长", required=False) or 14
    shock = data.get("shock")
    if shock is not None and not isinstance(shock, dict):
        raise ApiError("E4001", "冲击参数格式不正确", 400)
    result = scenario.run_scenario(
        db,
        user,
        variety_id,
        region_id,
        supply_shock=data.get("supply_shock", 0) or 0,
        demand_shock=data.get("demand_shock", 0) or 0,
        freight_shock=data.get("freight_shock", 0) or 0,
        horizon=horizon,
        name=data.get("name") or None,
        scenario_type=data.get("scenario_type") or "weather",
        shock=shock,
    )
    write_audit(
        db,
        user,
        "执行情景推演",
        "情景推演",
        f"品种={variety_id} 地区={region_id} 步长={horizon} 名称={result.get('name')}",
        client_ip(request),
    )
    return result


@router.get("/scenarios/templates")
def scenario_templates(
    user: Any = Depends(require_permission("scenario:view")),
):
    """情景推演模板列表。"""
    return ok(scenario.templates())


@router.get("/scenarios")
def scenarios_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: Any = Depends(require_permission("scenario:view")),
    db: Session = Depends(get_db),
):
    """情景推演历史记录（分页）。"""
    page, page_size = page_args(page, page_size)
    items, total = scenario.list_scenarios(db, page, page_size)
    return paged(items, total, page, page_size)


@router.post("/scenarios")
def scenarios_create(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("scenario:run")),
    db: Session = Depends(get_db),
):
    """执行情景推演：基于基线预测叠加供给 / 需求 / 运费等冲击。"""
    return ok(_run(_body_dict(body), request, user, db))


@router.post("/scenarios/run")
def scenarios_run(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("scenario:run")),
    db: Session = Depends(get_db),
):
    """执行情景推演（POST /api/scenarios 的别名）。"""
    return ok(_run(_body_dict(body), request, user, db))


@router.get("/scenarios/{scenario_id}")
def scenario_detail(
    scenario_id: int,
    user: Any = Depends(require_permission("scenario:view")),
    db: Session = Depends(get_db),
):
    """情景推演详情（含基线与情景对比序列）。"""
    return ok(scenario.get_scenario(db, scenario_id))


@router.delete("/scenarios/{scenario_id}")
def scenario_delete(
    scenario_id: int,
    request: Request,
    user: Any = Depends(require_permission("scenario:run")),
    db: Session = Depends(get_db),
):
    """删除情景推演记录。"""
    scenario.delete_scenario(db, scenario_id)
    write_audit(db, user, "删除情景推演", "情景推演", f"记录ID={scenario_id}", client_ip(request))
    return ok({"id": scenario_id})
