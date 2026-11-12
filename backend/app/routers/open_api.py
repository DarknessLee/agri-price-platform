"""开放 API（/api/open/v1）：面向外部系统的只读数据接口，以及调用方密钥治理。

鉴权：``Authorization: Bearer <JWT>`` 或 ``X-Api-Key: <client_key>``（见 services/open_api_gate.py）；
返回体统一为 {code,message,data}。
调用方治理端点：``/api/open-clients`` 列表 / 新建 / 修改 / 轮换 / 删除 / 用量统计。
"""

from __future__ import annotations

import secrets
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import OPEN_API_RATE_LIMIT
from ..database import get_db
from ..models import (
    AlertRecord,
    DataSource,
    ForecastResult,
    ModelVersion,
    OpenApiCall,
    OpenApiClient,
    PriceRecord,
    Region,
    Report,
    Variety,
)
from ..responses import ok
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services.open_api_gate import OpenApiPrincipal, open_api_guard

router = APIRouter(tags=["open-api"])

_MAX_LIMIT = 500
_RATE_LIMIT_MIN = 1
_RATE_LIMIT_MAX = 600


def _clamp(limit: int) -> int:
    return max(1, min(int(limit or 100), _MAX_LIMIT))


def _body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("E4001", "请求体格式不正确", 400)
    return body


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "是", "启用", "yes", "on")


def _rate_value(value: Any) -> int:
    if value is None:
        value = OPEN_API_RATE_LIMIT
    try:
        rate_limit = int(value)
    except (TypeError, ValueError):
        raise ApiError("E4001", "限流值必须为整数", 400)
    return max(_RATE_LIMIT_MIN, min(_RATE_LIMIT_MAX, rate_limit))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _mask_secret(secret: str | None) -> str:
    """密钥掩码：仅保留前 6 位 + ****。"""
    text = str(secret or "")
    return f"{text[:6]}****" if text else "****"


def _new_credentials() -> tuple[str, str]:
    return f"ak_{secrets.token_hex(8)}", f"sk_{secrets.token_hex(10)}"


# ============================ /open/v1 数据接口 ============================

def _variety(db: Session, code: str | None) -> Variety | None:
    if not code:
        return None
    return db.execute(select(Variety).where(Variety.code == code, Variety.enabled.is_(True))).scalars().first()


def _region(db: Session, code: str | None) -> Region | None:
    if not code:
        return None
    return db.execute(select(Region).where(Region.code == code, Region.enabled.is_(True))).scalars().first()


@router.get("/open/v1/prices")
def open_prices(
    principal: OpenApiPrincipal = Depends(open_api_guard),
    db: Session = Depends(get_db),
    variety_code: str | None = Query(None),
    region_code: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(100),
):
    stmt = select(PriceRecord, Variety.code, Region.code, Variety.unit).join(
        Variety, Variety.id == PriceRecord.variety_id
    ).join(Region, Region.id == PriceRecord.region_id)
    if variety_code:
        stmt = stmt.where(Variety.code == variety_code)
    if region_code:
        stmt = stmt.where(Region.code == region_code)
    if start:
        try:
            stmt = stmt.where(PriceRecord.price_date >= date.fromisoformat(start))
        except ValueError:
            pass
    if end:
        try:
            stmt = stmt.where(PriceRecord.price_date <= date.fromisoformat(end))
        except ValueError:
            pass
    limit = _clamp(limit)
    rows = db.execute(stmt.order_by(PriceRecord.price_date.desc(), PriceRecord.id.desc()).limit(limit)).all()
    items = [
        {
            "date": rec.price_date.isoformat(),
            "variety_code": vcode,
            "region_code": rcode,
            "market_type": rec.market_type,
            "price": round(float(rec.price or 0), 2),
            "unit": rec.unit or unit or "元/公斤",
        }
        for rec, vcode, rcode, unit in rows
    ]
    return ok({"items": items, "total": len(items)})


def _live_forecast(db: Session, user: Any, variety: Variety, region: Region, horizon: int) -> dict | None:
    try:
        from ..services import forecasting  # 延迟导入，避免服务尚未就绪时阻塞
    except Exception:
        return None
    if not hasattr(forecasting, "run_forecast"):
        return None
    try:
        payload = forecasting.run_forecast(db, user, variety.id, region.id, horizon=horizon)
    except Exception:
        db.rollback()
        return None
    if not isinstance(payload, dict):
        return None
    return payload


@router.get("/open/v1/forecast")
def open_forecast(
    principal: OpenApiPrincipal = Depends(open_api_guard),
    db: Session = Depends(get_db),
    variety_code: str = Query(...),
    region_code: str = Query(...),
    horizon: int = Query(7),
):
    variety = _variety(db, variety_code)
    region = _region(db, region_code)
    if not variety or not region:
        return ok({"variety_code": variety_code, "region_code": region_code, "model": None, "forecast": [], "mape": None})
    horizon = max(1, min(int(horizon or 7), 90))
    payload = _live_forecast(db, principal.user, variety, region, horizon)

    forecast: list[dict] = []
    model_info: dict | None = None
    mape: float | None = None
    if payload:
        model = payload.get("model") or {}
        model_info = {"key": model.get("key"), "name": model.get("name")} if model else None
        mape = model.get("mape") if model else None
        for item in payload.get("forecast") or []:
            forecast.append(
                {
                    "target_date": item.get("target_date"),
                    "point": item.get("point"),
                    "lower": item.get("lower"),
                    "upper": item.get("upper"),
                    "direction": item.get("direction", "持平"),
                }
            )
    if not forecast:
        stmt = (
            select(ForecastResult)
            .where(ForecastResult.variety_id == variety.id, ForecastResult.region_id == region.id)
            .order_by(ForecastResult.target_date.asc(), ForecastResult.id.asc())
            .limit(horizon * 6)
        )
        rows = db.execute(stmt).scalars().all()
        if rows:
            latest_date = rows[-1].forecast_date
            keep = [r for r in rows if r.forecast_date == latest_date]
            model = db.get(ModelVersion, keep[0].model_id) if keep and keep[0].model_id else None
            model_info = {"key": model.key, "name": model.name} if model else None
            mape = model.mape if model else None
            for r in keep[:horizon]:
                forecast.append(
                    {
                        "target_date": r.target_date.isoformat(),
                        "point": round(float(r.point), 2),
                        "lower": round(float(r.lower), 2),
                        "upper": round(float(r.upper), 2),
                        "direction": r.direction,
                    }
                )
    return ok(
        {
            "variety_code": variety.code,
            "region_code": region.code,
            "model": model_info,
            "forecast": forecast,
            "mape": round(float(mape), 2) if isinstance(mape, (int, float)) else None,
        }
    )


@router.get("/open/v1/alerts")
def open_alerts(
    principal: OpenApiPrincipal = Depends(open_api_guard),
    db: Session = Depends(get_db),
    level: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20),
):
    stmt = select(AlertRecord)
    if level:
        stmt = stmt.where(AlertRecord.level == level)
    if status:
        stmt = stmt.where(AlertRecord.status == status)
    rows = db.execute(stmt.order_by(AlertRecord.alert_date.desc(), AlertRecord.id.desc()).limit(_clamp(limit))).scalars().all()
    items = [
        {
            "id": r.id,
            "level": r.level,
            "title": r.title,
            "alert_date": r.alert_date.isoformat() if r.alert_date else None,
            "status": r.status,
        }
        for r in rows
    ]
    return ok({"items": items, "total": len(items)})


@router.get("/open/v1/reports")
def open_reports(
    principal: OpenApiPrincipal = Depends(open_api_guard),
    db: Session = Depends(get_db),
    report_type: str | None = Query(None),
    limit: int = Query(10),
):
    stmt = select(Report)
    if report_type:
        stmt = stmt.where(Report.report_type == report_type)
    rows = db.execute(stmt.order_by(Report.created_at.desc(), Report.id.desc()).limit(_clamp(limit))).scalars().all()
    items = [
        {
            "id": r.id,
            "title": r.title,
            "report_type": r.report_type,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
        }
        for r in rows
    ]
    return ok({"items": items, "total": len(items)})


@router.get("/open/v1/metrics")
def open_metrics(
    principal: OpenApiPrincipal = Depends(open_api_guard),
    db: Session = Depends(get_db),
):
    variety_count = db.scalar(select(func.count()).select_from(Variety).where(Variety.enabled.is_(True))) or 0
    region_count = db.scalar(select(func.count()).select_from(Region).where(Region.enabled.is_(True))) or 0
    record_count = db.scalar(select(func.count()).select_from(PriceRecord)) or 0
    normal_count = db.scalar(select(func.count()).select_from(PriceRecord).where(PriceRecord.quality_flag == "正常")) or 0
    latest = db.scalar(select(func.max(PriceRecord.price_date)))
    source_count = db.scalar(select(func.count()).select_from(DataSource)) or 0
    alert_open = db.scalar(select(func.count()).select_from(AlertRecord).where(AlertRecord.status == "待处理")) or 0
    completeness = round(normal_count * 100.0 / record_count, 2) if record_count else 0.0
    return ok(
        {
            "variety_count": variety_count,
            "region_count": region_count,
            "source_count": source_count,
            "record_count": record_count,
            "normal_record_count": normal_count,
            "completeness": completeness,
            "latest_price_date": latest.isoformat() if latest else None,
            "open_alert_count": alert_open,
            "generated_at": date.today().isoformat(),
        }
    )


# ============================ /open-clients 密钥治理 ============================

def _client_row(client: OpenApiClient) -> dict:
    return {
        "id": int(client.id),
        "name": client.name or "",
        "client_key": client.client_key or "",
        "secret_masked": _mask_secret(client.secret),
        "enabled": bool(client.enabled),
        "rate_limit": int(client.rate_limit or OPEN_API_RATE_LIMIT),
        "call_count": int(client.call_count or 0),
        "last_call_at": _iso(client.last_call_at),
        "created_at": _iso(client.created_at),
        "description": client.description or "",
    }


def _get_client(db: Session, client_id: int) -> OpenApiClient:
    client = db.get(OpenApiClient, int(client_id))
    if client is None:
        raise ApiError("E4040", "调用方不存在", 404)
    return client


@router.get("/open-clients")
def open_clients_list(
    user: Any = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """调用方列表（secret 掩码）。"""
    rows = db.execute(select(OpenApiClient).order_by(OpenApiClient.id)).scalars().all()
    return ok([_client_row(row) for row in rows])


@router.post("/open-clients")
def open_clients_create(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """新建调用方：生成 ak_/sk_ 密钥，明文仅本次返回。"""
    data = _body_dict(body)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ApiError("E4001", "请填写调用方名称", 400)
    if db.execute(select(OpenApiClient).where(OpenApiClient.name == name)).scalars().first() is not None:
        raise ApiError("E4090", "调用方名称已存在", 409)
    client_key, secret = _new_credentials()
    client = OpenApiClient(
        name=name[:64],
        client_key=client_key,
        secret=secret,
        enabled=_to_bool(data.get("enabled"), True),
        rate_limit=_rate_value(data.get("rate_limit", OPEN_API_RATE_LIMIT)),
        call_count=0,
        last_call_at=None,
        description=str(data.get("description") or "")[:255],
        created_at=datetime.now(),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    write_audit(
        db,
        user,
        "新建开放API调用方",
        "开放API",
        f"调用方ID={client.id} 名称={client.name} 限流={client.rate_limit}/分钟",
        client_ip(request),
    )
    return ok(
        {
            "id": int(client.id),
            "name": client.name,
            "client_key": client.client_key,
            "secret": client.secret,
            "enabled": bool(client.enabled),
            "rate_limit": int(client.rate_limit),
        }
    )


@router.put("/open-clients/{client_id}")
def open_clients_update(
    client_id: int,
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """修改调用方（启用状态 / 限流 / 说明），返回掩码后的行。"""
    data = _body_dict(body)
    client = _get_client(db, client_id)
    if "enabled" in data:
        client.enabled = _to_bool(data.get("enabled"), bool(client.enabled))
    if "rate_limit" in data:
        client.rate_limit = _rate_value(data.get("rate_limit"))
    if "description" in data:
        client.description = str(data.get("description") or "")[:255]
    db.add(client)
    db.commit()
    db.refresh(client)
    write_audit(
        db,
        user,
        "修改开放API调用方",
        "开放API",
        f"调用方ID={client.id} 启用={client.enabled} 限流={client.rate_limit}/分钟",
        client_ip(request),
    )
    return ok(_client_row(client))


@router.post("/open-clients/{client_id}/rotate")
def open_clients_rotate(
    client_id: int,
    request: Request,
    user: Any = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """轮换密钥：同时更新 client_key 与 secret，明文仅本次返回。"""
    client = _get_client(db, client_id)
    client_key, secret = _new_credentials()
    client.client_key = client_key
    client.secret = secret
    db.add(client)
    db.commit()
    db.refresh(client)
    write_audit(db, user, "轮换开放API密钥", "开放API", f"调用方ID={client.id} 名称={client.name}", client_ip(request))
    return ok({"id": int(client.id), "client_key": client.client_key, "secret": client.secret})


@router.delete("/open-clients/{client_id}")
def open_clients_delete(
    client_id: int,
    request: Request,
    user: Any = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """删除调用方及其调用流水。"""
    client = _get_client(db, client_id)
    deleted_calls = db.execute(delete(OpenApiCall).where(OpenApiCall.client_id == int(client.id))).rowcount or 0
    db.delete(client)
    db.commit()
    write_audit(
        db,
        user,
        "删除开放API调用方",
        "开放API",
        f"调用方ID={client_id} 清理流水={deleted_calls}",
        client_ip(request),
    )
    return ok({"id": int(client_id), "deleted": True})


@router.get("/open-clients/{client_id}/usage")
def open_clients_usage(
    client_id: int,
    days: int = Query(default=7, ge=1, le=90),
    user: Any = Depends(require_permission("data:view")),
    db: Session = Depends(get_db),
):
    """调用方近 N 天用量：按日调用量、平均耗时、错误率、热门路径与最近调用时间。"""
    client = _get_client(db, client_id)
    today = date.today()
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time())
    rows = db.execute(
        select(OpenApiCall.created_at, OpenApiCall.status, OpenApiCall.elapsed_ms, OpenApiCall.path)
        .where(OpenApiCall.client_id == int(client.id))
        .where(OpenApiCall.created_at >= start_dt)
    ).all()

    per_day: dict[str, int] = {}
    path_counter: Counter[str] = Counter()
    total_ms = 0
    errors = 0
    for created_at, status, elapsed_ms, path in rows:
        day_key = created_at.date().isoformat() if created_at else start.isoformat()
        per_day[day_key] = per_day.get(day_key, 0) + 1
        path_counter[str(path or "")] += 1
        total_ms += int(elapsed_ms or 0)
        if int(status or 0) >= 400:
            errors += 1

    total = len(rows)
    day_items = [
        {"date": (today - timedelta(days=offset)).isoformat(), "count": int(per_day.get((today - timedelta(days=offset)).isoformat(), 0))}
        for offset in range(days - 1, -1, -1)
    ]
    last_call_at = _iso(client.last_call_at)
    if last_call_at is None:
        stamps = [row[0] for row in rows if row[0] is not None]
        if stamps:
            last_call_at = _iso(max(stamps))
    return ok(
        {
            "client_id": int(client.id),
            "days": day_items,
            "total": total,
            "avg_elapsed_ms": int(round(total_ms / total)) if total else 0,
            "error_rate": round(errors * 100.0 / total, 2) if total else 0.0,
            "top_paths": [{"path": path, "count": count} for path, count in path_counter.most_common(5)],
            "last_call_at": last_call_at,
        }
    )
