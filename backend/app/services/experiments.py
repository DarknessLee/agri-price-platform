"""模型实验记录服务（契约 M3 §4）：训练实验落库 + 参数/指标归档到对象存储。

设计要点：
- 每次 ``train_model`` 为 4 个算法版本各写一条 ``model_run``，默认 trigger=手动；
- ``metrics`` 保存 mape/rmse/direction_acc/rows，``params`` 保存算法超参、组合权重与留出配置；
- 训练产物 JSON 通过 ``storage.put_bytes`` 归档，对象键为 ``models/{品种}_{地区}_{算法}_{版本}.json``，
  MinIO 不可用时 storage 自动写本地 ``.runtime/storage`` 同键路径，业务无感知；
- 实验记录与模型版本同事务提交；归档失败只记录日志，不阻断训练主流程；
- 漂移模型重训编排也放在本模块，路由层保持轻量。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache, storage
from ..database import now
from ..models import ModelRun, ModelVersion, Region, Variety
from ..security import ApiError

logger = logging.getLogger(__name__)

TRIGGER_MANUAL = "手动"
TRIGGER_SCHEDULED = "定时"

RUN_SUCCESS = "成功"
RUN_FAILED = "失败"

# 各算法的训练超参：与 services/forecasting.py 中的拟合实现保持一致，写入实验记录便于复现。
HYPERPARAMETERS: dict[str, dict[str, Any]] = {
    "seasonal": {
        "model": "季节分解基线",
        "trend_window": 365,
        "seasonal_periods": 7,
        "annual_periods": 365,
        "residual_model": "AR(1)",
        "log_transform": True,
    },
    "holt_winters": {
        "model": "Holt-Winters 三次指数平滑",
        "trend": "add",
        "seasonal": "add",
        "seasonal_periods": 7,
        "damped_trend": True,
        "initialization_method": "heuristic",
        "log_transform": True,
        "optimized": True,
    },
    "gbr": {
        "model": "GradientBoostingRegressor",
        "n_estimators": "min(160, max(60, 样本数 // 6))",
        "learning_rate": 0.08,
        "max_depth": 3,
        "min_samples_leaf": 6,
        "subsample": 0.9,
        "random_state": 42,
        "features": "22 维：滞后(1/7/14/30/365)、滚动均值与标准差(7/30)、季节三角、星期、节假日、同比/环比、成本/运费/天气指数、波动率",
    },
    "ensemble": {
        "model": "回测加权组合",
        "weighting": "holdout MAPE 倒数加权",
        "weights": None,
    },
}


def hyperparameters(model_key: str) -> dict:
    """返回指定算法的超参副本（避免调用方修改模块级常量）。"""
    return dict(HYPERPARAMETERS.get(str(model_key or ""), {}))


def _loads(text: Any, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) or default is None else default


def _loads_dict(text: Any) -> dict:
    value = _loads(text, {})
    return value if isinstance(value, dict) else {}


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def operator_name(user: Any) -> str:
    """从当前用户提取操作人名称，供实验记录与失败回溯使用。"""
    name = ""
    if user is not None:
        name = getattr(user, "display_name", None) or getattr(user, "username", None) or ""
    return str(name or "system")[:64]


def _metrics_of(model: ModelVersion) -> dict:
    return {
        "mape": round(float(model.mape or 0), 4),
        "rmse": round(float(model.rmse or 0), 4),
        "direction_acc": round(float(model.direction_acc or 0), 2),
        "rows": int(model.rows or 0),
    }


def _params_of(model: ModelVersion) -> dict:
    raw = _loads_dict(model.params)
    payload: dict[str, Any] = {
        "algorithm": str(model.key or ""),
        "hyperparameters": hyperparameters(model.key),
    }
    for field in ("weights", "holdout_days", "residual_std", "features"):
        value = raw.get(field)
        if value not in (None, [], {}):
            payload[field] = value
    return payload


def _archive(model: ModelVersion, metrics: dict, params: dict) -> str:
    """把训练产物（指标+参数）归档到对象存储，返回对象键；失败只记录日志。"""
    try:
        key = storage.model_key(
            int(model.variety_id or 0),
            int(model.region_id or 0),
            str(model.key or ""),
            str(model.version or ""),
        )
        content = _dumps(
            {
                "model": {
                    "id": model.id,
                    "key": model.key,
                    "name": model.name,
                    "algorithm": model.algorithm,
                    "variety_id": int(model.variety_id or 0),
                    "region_id": int(model.region_id or 0),
                    "version": model.version,
                },
                "metrics": metrics,
                "params": params,
                "archived_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        storage.put_bytes(key, content.encode("utf-8"), content_type="application/json")
        return key
    except Exception:  # pragma: no cover - 存储异常时保留本地 joblib 工件
        logger.exception("训练产物归档失败：model=%s version=%s", getattr(model, "id", None), getattr(model, "version", ""))
        return ""


def record_training(
    db: Session,
    models: list[ModelVersion],
    *,
    trigger: str = TRIGGER_MANUAL,
    operator: str = "system",
    duration_ms: int = 0,
    commit: bool = False,
) -> list[ModelRun]:
    """为一次训练产出的每个模型写实验记录，并归档指标/参数到对象存储。"""
    trigger = TRIGGER_SCHEDULED if str(trigger) == TRIGGER_SCHEDULED else TRIGGER_MANUAL
    operator = str(operator or "system")[:64]
    duration_ms = max(0, int(duration_ms or 0))
    runs: list[ModelRun] = []
    for model in models:
        metrics = _metrics_of(model)
        params = _params_of(model)
        artifact_key = _archive(model, metrics, params)
        run = ModelRun(
            model_id=int(model.id or 0),
            key=str(model.key or ""),
            name=str(model.name or "")[:128],
            algorithm=str(model.algorithm or "")[:32],
            variety_id=int(model.variety_id or 0),
            region_id=int(model.region_id or 0),
            version=str(model.version or "")[:32],
            trigger=trigger,
            status=RUN_SUCCESS,
            params=_dumps(params),
            metrics=_dumps(metrics),
            rows=int(model.rows or 0),
            duration_ms=duration_ms,
            artifact_key=artifact_key,
            operator=operator,
            created_at=now(),
        )
        db.add(run)
        runs.append(run)
    db.flush()
    return runs


def record_failure(
    db: Session,
    *,
    variety_id: int,
    region_id: int,
    key: str = "",
    name: str = "",
    algorithm: str = "",
    version: str = "",
    trigger: str = TRIGGER_MANUAL,
    operator: str = "system",
    duration_ms: int = 0,
    error: str = "",
    commit: bool = False,
) -> ModelRun:
    """记录一次训练失败（不产生 ModelVersion），便于在实验记录里回溯原因。"""
    run = ModelRun(
        model_id=0,
        key=str(key or "")[:32],
        name=str(name or "")[:128],
        algorithm=str(algorithm or "")[:32],
        variety_id=int(variety_id or 0),
        region_id=int(region_id or 0),
        version=str(version or "")[:32],
        trigger=TRIGGER_SCHEDULED if str(trigger) == TRIGGER_SCHEDULED else TRIGGER_MANUAL,
        status=RUN_FAILED,
        params=_dumps({"error": str(error or "")[:500]}),
        metrics="{}",
        rows=0,
        duration_ms=max(0, int(duration_ms or 0)),
        artifact_key="",
        operator=str(operator or "system")[:64],
        created_at=now(),
    )
    db.add(run)
    if commit:
        db.commit()
    else:
        db.flush()
    return run


def serialize_run(run: ModelRun, variety_name: str = "", region_name: str = "") -> dict:
    """实验记录对外结构（契约 M3 §4）。"""
    return {
        "id": run.id,
        "model_id": run.model_id,
        "key": run.key,
        "name": run.name,
        "algorithm": run.algorithm,
        "variety": variety_name,
        "region": region_name,
        "version": run.version,
        "trigger": run.trigger,
        "status": run.status,
        "params": _loads_dict(run.params),
        "metrics": _loads_dict(run.metrics),
        "rows": int(run.rows or 0),
        "duration_ms": int(run.duration_ms or 0),
        "artifact_key": run.artifact_key,
        "operator": run.operator,
        "created_at": run.created_at.strftime("%Y-%m-%dT%H:%M:%S") if run.created_at else "",
    }


def list_runs(
    db: Session,
    variety_id: Any = None,
    region_id: Any = None,
    limit: Any = 50,
) -> tuple[list[dict], int]:
    """按品种/地区筛选实验记录，按时间倒序返回 (列表, 总数)。"""
    try:
        limit_value = max(1, min(200, int(limit or 50)))
    except (TypeError, ValueError):
        raise ApiError("E4001", "返回条数必须为整数", 400)
    conditions = []
    if variety_id not in (None, ""):
        try:
            conditions.append(ModelRun.variety_id == int(variety_id))
        except (TypeError, ValueError):
            raise ApiError("E4001", "品种参数必须为整数", 400)
    if region_id not in (None, ""):
        try:
            conditions.append(ModelRun.region_id == int(region_id))
        except (TypeError, ValueError):
            raise ApiError("E4001", "地区参数必须为整数", 400)

    count_stmt = select(func.count(ModelRun.id))
    list_stmt = select(ModelRun).order_by(ModelRun.id.desc()).limit(limit_value)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar() or 0)
    rows = db.execute(list_stmt).scalars().all()

    varieties = {int(v.id): v.name for v in db.execute(select(Variety)).scalars().all()}
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    items = [
        serialize_run(
            run,
            varieties.get(int(run.variety_id or 0), ""),
            regions.get(int(run.region_id or 0), ""),
        )
        for run in rows
    ]
    return items, total


def retrain_drifted(db: Session, user: Any = None, limit: Any = 5, window: Any = 90) -> dict:
    """重训漂移模型：只处理 governance.model_drift 判为「漂移」的组合，最多 limit 组。"""
    from . import forecasting, governance  # 延迟导入，避免与 forecasting 循环依赖

    try:
        limit_value = max(1, min(20, int(limit if limit is not None else 5)))
    except (TypeError, ValueError):
        raise ApiError("E4001", "重训数量必须为整数", 400)
    try:
        window_value = int(window if window is not None else 90)
    except (TypeError, ValueError):
        raise ApiError("E4001", "监控窗口必须为整数", 400)
    if window_value < 30 or window_value > 365:
        raise ApiError("E4001", "监控窗口需在 30~365 天之间", 400)

    payload = governance.model_drift(db, window_value)
    drifted = [
        item
        for item in payload.get("items", [])
        if item.get("drift_level") == governance.DRIFT_DRIFT
    ][:limit_value]

    operator = operator_name(user)
    items: list[dict] = []
    trained = 0
    failed = 0
    for item in drifted:
        variety_name = str(item.get("variety") or "")
        region_name = str(item.get("region") or "")
        started = time.perf_counter()
        model = None
        try:
            model = forecasting.get_model(db, int(item.get("model_id")))
            forecasting.train_model(
                db,
                int(model.variety_id),
                int(model.region_id),
                commit=True,
                notify=True,
                trigger=TRIGGER_MANUAL,
                operator=operator,
            )
            trained += 1
            items.append(
                {
                    "variety": variety_name,
                    "region": region_name,
                    "psi": item.get("psi"),
                    "mape": item.get("mape"),
                    "status": RUN_SUCCESS,
                }
            )
        except ApiError as exc:
            failed += 1
            duration_ms = int((time.perf_counter() - started) * 1000)
            try:
                record_failure(
                    db,
                    variety_id=int(model.variety_id) if model is not None else int(item.get("variety_id") or 0),
                    region_id=int(model.region_id) if model is not None else int(item.get("region_id") or 0),
                    key=str(getattr(model, "key", "") or ""),
                    name=str(getattr(model, "name", "") or ""),
                    algorithm=str(getattr(model, "algorithm", "") or ""),
                    version=str(getattr(model, "version", "") or ""),
                    trigger=TRIGGER_MANUAL,
                    operator=operator,
                    duration_ms=duration_ms,
                    error=exc.message,
                    commit=True,
                )
            except Exception:  # pragma: no cover - 失败记录写入异常不覆盖原始错误
                logger.exception("重训失败记录写入失败：%s·%s", variety_name, region_name)
                db.rollback()
            items.append(
                {
                    "variety": variety_name,
                    "region": region_name,
                    "psi": item.get("psi"),
                    "mape": item.get("mape"),
                    "status": RUN_FAILED,
                    "message": exc.message,
                }
            )
        except Exception as exc:  # pragma: no cover - 训练过程中的非业务异常
            failed += 1
            logger.exception("重训漂移模型异常：%s·%s", variety_name, region_name)
            try:
                db.rollback()
            except Exception:
                pass
            items.append(
                {
                    "variety": variety_name,
                    "region": region_name,
                    "psi": item.get("psi"),
                    "mape": item.get("mape"),
                    "status": RUN_FAILED,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )

    # 训练后模型状态已变化，清掉漂移缓存，下次查询立即反映最新指标
    try:
        cache.delete(cache.make_key("models", "drift", window_value))
    except Exception:  # pragma: no cover - 缓存不可用时忽略
        logger.exception("清理漂移缓存失败")

    return {"trained": trained, "failed": failed, "items": items}
