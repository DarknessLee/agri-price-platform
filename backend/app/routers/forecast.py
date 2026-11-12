"""预测分析路由（契约 §5）：单次预测、结果查询、批量预测与导出、性能汇总。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..responses import ok
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services import forecasting

router = APIRouter(tags=["预测分析"])


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


@router.post("/forecast/run")
def forecast_run(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("forecast:run")),
    db: Session = Depends(get_db),
):
    """执行单次预测：返回历史序列、逐日预测点、区间、方向与特征贡献。"""
    data = _body_dict(body)
    variety_id = _as_int(data.get("variety_id"), "品种")
    region_id = _as_int(data.get("region_id"), "地区")
    horizon = _as_int(data.get("horizon"), "预测步长", required=False) or forecasting.DEFAULT_HORIZON
    model_key = data.get("model_key") or None
    if model_key is not None and str(model_key) not in forecasting.MODEL_KEYS:
        raise ApiError("E4001", f"不支持的模型标识：{model_key}", 400)
    result = forecasting.run_forecast(db, user, variety_id, region_id, horizon, model_key)
    write_audit(
        db,
        user,
        "执行预测",
        "预测分析",
        f"品种={variety_id} 地区={region_id} 步长={horizon} 模型={model_key or '组合模型'}",
        client_ip(request),
    )
    return ok(result)


@router.get("/forecast/results")
def forecast_results(
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """预测结果列表（按创建时间倒序，非分页）。"""
    return ok(forecasting.forecast_results_list(db, variety_id, region_id, limit))


@router.get("/forecast/result/{result_id}")
def forecast_result_detail(
    result_id: int,
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """预测结果详情（复用持久化的完整预测载荷）。"""
    return ok(forecasting.forecast_result_detail(db, result_id))


@router.delete("/forecast/results/{result_id}")
def forecast_result_delete(
    result_id: int,
    request: Request,
    user: Any = Depends(require_permission("forecast:run")),
    db: Session = Depends(get_db),
):
    """删除预测结果。"""
    forecasting.delete_forecast_result(db, result_id)
    write_audit(db, user, "删除预测结果", "预测分析", f"结果ID={result_id}", client_ip(request))
    return ok({"id": result_id})


@router.post("/forecast/batch")
def forecast_batch(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("forecast:run")),
    db: Session = Depends(get_db),
):
    """批量预测（同步执行，单次不超过 200 条）。"""
    data = _body_dict(body)
    horizon = _as_int(data.get("horizon"), "预测步长", required=False) or forecasting.DEFAULT_HORIZON
    model_key = data.get("model_key") or None
    result = forecasting.run_forecast_batch(
        db,
        user,
        variety_ids=data.get("variety_ids"),
        region_ids=data.get("region_ids"),
        horizon=horizon,
        model_key=model_key,
    )
    write_audit(
        db,
        user,
        "批量预测",
        "预测分析",
        f"批次={result.get('batch_id')} 总数={result.get('total')} 完成={result.get('done')}",
        client_ip(request),
    )
    return ok(result)


@router.get("/forecast/batches")
def forecast_batches(
    limit: int = Query(default=20, ge=1, le=200),
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """批量预测批次列表。"""
    return ok(forecasting.batch_list(db, limit))


@router.get("/forecast/batch/{batch_id}")
def forecast_batch_detail(
    batch_id: int,
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """批量预测详情。"""
    return ok(forecasting.get_batch_detail(db, batch_id))


@router.get("/forecast/batch/{batch_id}/export")
def forecast_batch_export(
    batch_id: int,
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """导出批量预测结果为 CSV。"""
    rows = forecasting.batch_export_rows(db, batch_id)
    return _csv_response(rows, f"forecast_batch_{batch_id}.csv")


@router.get("/forecast/performance")
def forecast_performance(
    user: Any = Depends(require_permission("forecast:view")),
    db: Session = Depends(get_db),
):
    """预测性能汇总：平均 MAPE、方向准确率、时间序列与品种分布。"""
    return ok(forecasting.forecast_performance(db))
