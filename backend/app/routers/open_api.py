"""开放 API（/api/open/v1）：面向外部系统的只读数据接口。

鉴权与主站一致（Bearer JWT）；返回体统一为 {code,message,data}。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AlertRecord,
    DataSource,
    ForecastResult,
    ModelVersion,
    PriceRecord,
    Region,
    Report,
    Variety,
)
from ..responses import ok
from ..security import CurrentUser

router = APIRouter(prefix="/open/v1", tags=["open-api"])

_MAX_LIMIT = 500


def _clamp(limit: int) -> int:
    return max(1, min(int(limit or 100), _MAX_LIMIT))


def _variety(db: Session, code: str | None) -> Variety | None:
    if not code:
        return None
    return db.execute(select(Variety).where(Variety.code == code, Variety.enabled.is_(True))).scalars().first()


def _region(db: Session, code: str | None) -> Region | None:
    if not code:
        return None
    return db.execute(select(Region).where(Region.code == code, Region.enabled.is_(True))).scalars().first()


@router.get("/prices")
def open_prices(
    user: CurrentUser,
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


@router.get("/forecast")
def open_forecast(
    user: CurrentUser,
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
    payload = _live_forecast(db, user, variety, region, horizon)

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


@router.get("/alerts")
def open_alerts(
    user: CurrentUser,
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


@router.get("/reports")
def open_reports(
    user: CurrentUser,
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


@router.get("/metrics")
def open_metrics(user: CurrentUser, db: Session = Depends(get_db)):
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
