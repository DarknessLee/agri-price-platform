"""模型管理路由（契约 §6）：模型列表、训练、启用、回测与算法对比。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Region, Variety
from ..responses import ok
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services import forecasting, governance

router = APIRouter(tags=["模型管理"])


def _body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("E4001", "请求体格式不正确", 400)
    return body


def _as_int(value: Any, label: str, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise ApiError("E4001", f"请填写{label}", 400)
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("E4001", f"{label}必须为整数", 400)


def _name_of(db: Session, model: Any) -> tuple[str, str]:
    variety = db.get(Variety, int(model.variety_id)) if model.variety_id else None
    region = db.get(Region, int(model.region_id)) if model.region_id else None
    return (variety.name if variety else ""), (region.name if region else "")


def _params_of(model: Any) -> dict:
    try:
        params = json.loads(model.params or "{}")
    except (ValueError, TypeError):
        params = {}
    return params if isinstance(params, dict) else {}


def _model_payload(db: Session, model: Any) -> dict:
    variety_name, region_name = _name_of(db, model)
    data = forecasting.serialize_model(model, variety_name, region_name)
    params = _params_of(model)
    data["params"] = params
    data["weights"] = params.get("weights")
    data["feature_importance"] = params.get("feature_importance") or []
    data["holdout"] = params.get("holdout") or {}
    return data


@router.get("/models")
def models_list(
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    key: str | None = Query(default=None),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """模型列表，可按品种 / 地区 / 模型标识筛选。"""
    return ok(forecasting.list_models(db, variety_id, region_id, key))


@router.get("/models/drift")
def models_drift(
    window: int = Query(default=90),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """模型漂移监控：特征分布 PSI、近期回测 MAPE 与漂移等级（结果缓存 120 秒）。"""
    return ok(governance.model_drift(db, window))


@router.get("/models/compare")
def models_compare(
    variety_id: int = Query(...),
    region_id: int = Query(...),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """同一品种×地区下四种算法的指标对比。"""
    return ok(forecasting.compare_models(db, variety_id, region_id))


@router.post("/models/train")
def models_train(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("model:manage")),
    db: Session = Depends(get_db),
):
    """训练模型：指定品种与地区时训练四种算法；缺省为全部启用的品种×地区补齐组合模型。"""
    data = _body_dict(body)
    variety_id = _as_int(data.get("variety_id"), "品种")
    region_id = _as_int(data.get("region_id"), "地区")
    model_key = data.get("model_key") or None
    if model_key is not None and str(model_key) not in forecasting.MODEL_KEYS:
        raise ApiError("E4001", f"不支持的模型标识：{model_key}", 400)

    models = forecasting.train_models_for(
        db, variety_id=variety_id, region_id=region_id, model_key=model_key
    )
    if not models:
        raise ApiError("E4001", "暂无可用价格数据，无法训练模型", 400)
    target = next((item for item in models if model_key and item.key == model_key), None)
    if target is None:
        target = next((item for item in models if item.is_active), None)
    if target is None:
        target = models[-1]
    payload = _model_payload(db, target)
    write_audit(
        db,
        user,
        "训练模型",
        "模型管理",
        f"品种={variety_id or '全部'} 地区={region_id or '全部'} 模型={model_key or '全部算法'}",
        client_ip(request),
    )
    return ok(payload)


@router.get("/models/{model_id}")
def model_detail(
    model_id: int,
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """模型详情（含训练参数、权重与特征重要性）。"""
    model = forecasting.get_model(db, model_id)
    return ok(_model_payload(db, model))


@router.post("/models/{model_id}/activate")
def model_activate(
    model_id: int,
    request: Request,
    user: Any = Depends(require_permission("model:manage")),
    db: Session = Depends(get_db),
):
    """启用指定模型为对应品种×地区的在线模型（同一组合仅保留一个 active）。"""
    model = forecasting.activate_model(db, model_id)
    write_audit(db, user, "启用模型", "模型管理", f"模型ID={model.id} 名称={model.name}", client_ip(request))
    return ok({"ok": True, "active_id": model.id})


@router.get("/models/{model_id}/backtest")
def model_backtest(
    model_id: int,
    window: int = Query(default=60, ge=7, le=180),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """模型滚动回测：逐日实际值 / 预测值 / 区间与 MAPE、RMSE、方向准确率。"""
    model = forecasting.get_model(db, model_id)
    return ok(forecasting.get_backtest(db, model, window))
