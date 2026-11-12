"""驾驶舱接口（契约 §3）：总览指标、价格指数趋势、区域热力、品类占比、最新预警与预测摘要。"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db, now
from ..models import (
    AlertRecord,
    FeatureRecord,
    ForecastResult,
    Market,
    ModelVersion,
    PriceRecord,
    Region,
    Variety,
)
from ..responses import ok
from ..security import require_permission
from ..services import pricing, quality

router = APIRouter(prefix="/dashboard", tags=["驾驶舱"])


def _fmt_date(value) -> str | None:
    """日期 -> YYYY-MM-DD。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _fmt_time(value) -> str | None:
    """时间 -> YYYY-MM-DDTHH:MM:SS。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _avg(query, db: Session) -> float | None:
    """执行聚合查询并取首列；空结果返回 None。"""
    value = db.execute(query).scalar()
    return float(value) if value is not None else None


def _latest_alert_date(db: Session) -> date | None:
    """最近一条预警日期。"""
    return db.execute(select(func.max(AlertRecord.alert_date))).scalar()


@router.get("/summary")
def dashboard_summary(
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """驾驶舱总览卡片。"""
    variety_count = int(db.execute(select(func.count(Variety.id))).scalar() or 0)
    region_count = int(db.execute(select(func.count(Region.id))).scalar() or 0)
    market_count = int(db.execute(select(func.count(Market.id))).scalar() or 0)
    record_count = int(db.execute(select(func.count(PriceRecord.id))).scalar() or 0)
    latest = pricing.latest_price_date(db)

    avg_price = 0.0
    if latest:
        value = _avg(
            select(func.avg(PriceRecord.price)).where(PriceRecord.price_date == latest), db
        )
        avg_price = pricing.r2(value) or 0.0

    # 同比：优先特征表口径，缺失时用「最新均价 vs 一年前均价」回算
    latest_feature_date = db.execute(select(func.max(FeatureRecord.calc_date))).scalar()
    yoy = None
    if latest_feature_date:
        yoy = _avg(
            select(func.avg(FeatureRecord.yoy_pct)).where(
                FeatureRecord.calc_date == latest_feature_date
            ),
            db,
        )
    if yoy is None and latest:
        base = _avg(
            select(func.avg(PriceRecord.price)).where(
                PriceRecord.price_date >= latest - timedelta(days=400),
                PriceRecord.price_date <= latest - timedelta(days=330),
            ),
            db,
        )
        yoy = pricing.pct_change(avg_price, base)
    yoy = 0.0 if yoy is None else pricing.r2(yoy)

    alert_open = int(
        db.execute(
            select(func.count(AlertRecord.id)).where(AlertRecord.status == "待处理")
        ).scalar()
        or 0
    )
    today = date.today()
    alert_today = int(
        db.execute(
            select(func.count(AlertRecord.id)).where(AlertRecord.alert_date == today)
        ).scalar()
        or 0
    )
    if alert_today == 0:
        # 数据按最新日期归档时，「今日预警」回落到最近预警日
        anchor = _latest_alert_date(db)
        if anchor:
            alert_today = int(
                db.execute(
                    select(func.count(AlertRecord.id)).where(
                        AlertRecord.alert_date == anchor,
                        AlertRecord.status == "待处理",
                    )
                ).scalar()
                or 0
            )

    mape = _avg(
        select(func.avg(ModelVersion.mape)).where(ModelVersion.is_active.is_(True)), db
    )
    direction_acc = _avg(
        select(func.avg(ModelVersion.direction_acc)).where(ModelVersion.is_active.is_(True)),
        db,
    )
    if mape is None:
        mape = _avg(select(func.avg(ModelVersion.mape)).where(ModelVersion.mape > 0), db)
    if direction_acc is None:
        direction_acc = _avg(
            select(func.avg(ModelVersion.direction_acc)).where(ModelVersion.direction_acc > 0),
            db,
        )

    last_forecast_at = db.execute(select(func.max(ForecastResult.created_at))).scalar()

    return ok(
        {
            "kpi": {
                "variety_count": variety_count,
                "region_count": region_count,
                "market_count": market_count,
                "record_count": record_count,
                "avg_price": avg_price,
                "yoy_pct": yoy,
                "alert_open": alert_open,
                "alert_today": alert_today,
                "avg_mape": pricing.r2(mape) if mape is not None else 0.0,
                "direction_acc": pricing.r2(direction_acc) if direction_acc is not None else 0.0,
                "completeness": quality.completeness(db),
            },
            "latest_price_date": _fmt_date(latest),
            "last_forecast_at": _fmt_time(last_forecast_at),
            "updated_at": _fmt_time(now()),
        }
    )


@router.get("/trend")
def dashboard_trend(
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=3650),
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """价格指数趋势：未指定品种时返回综合均价 + 分品类序列。"""
    days = max(1, int(days or 90))
    anchor = pricing.latest_price_date(db, variety_id=variety_id) or date.today()
    start = anchor - timedelta(days=days - 1)
    series: list[dict] = []
    dates: list[date] = []

    if variety_id:
        variety = pricing.get_variety(db, variety_id)
        points = pricing.daily_points(
            db, variety_id=variety_id, region_id=region_id, start=start, end=anchor
        )
        dates = [day for day, _ in points]
        values = [pricing.r2(price) for _, price in points]
        series.append({"name": f"{variety.name}均价", "values": values})
        latest_price = values[-1] if values else 0.0
        change = pricing.pct_change(latest_price, values[-2]) if len(values) > 1 else None
        unit = variety.unit or pricing.DEFAULT_UNIT
    else:
        all_dates, matrix = pricing.daily_mean_by_variety(
            db, region_id=region_id, start=start, end=anchor
        )
        dates = all_dates
        varieties = db.execute(select(Variety).order_by(Variety.sort, Variety.id)).scalars().all()
        for variety in varieties:
            price_map = matrix.get(variety.id) or {}
            if not price_map:
                continue
            series.append(
                {
                    "name": variety.name,
                    "values": [pricing.r2(price_map.get(day)) for day in dates],
                }
            )
        # 综合均价：各品种当日均价的算术平均
        combined: list[float | None] = []
        for index in range(len(dates)):
            column = [item["values"][index] for item in series if item["values"][index] is not None]
            combined.append(pricing.r2(statistics.fmean(column)) if column else None)
        if combined:
            series.insert(0, {"name": "综合均价", "values": combined})
        values = [value for value in combined if value is not None]
        latest_price = values[-1] if values else 0.0
        change = pricing.pct_change(latest_price, values[-2]) if len(values) > 1 else None
        unit = pricing.DEFAULT_UNIT

    # 同比：特征表（按品种/地区）缺失时按一年前价格回算
    yoy = None
    if variety_id:
        snapshot = pricing.feature_snapshot(db, variety_id=variety_id, region_id=region_id)
        yoy = snapshot.get("yoy_pct")
        if yoy is None:
            base = pricing.price_one_year_ago(
                db, variety_id=variety_id, region_id=region_id, anchor=anchor
            )
            yoy = pricing.pct_change(latest_price, base)
    yoy = 0.0 if yoy is None else pricing.r2(yoy)

    return ok(
        {
            "dates": [_fmt_date(day) for day in dates],
            "series": series,
            "unit": unit,
            "latest": {
                "date": _fmt_date(dates[-1]) if dates else None,
                "price": pricing.r2(latest_price),
                "yoy_pct": yoy,
                "change": pricing.r2(change) if change is not None else 0.0,
            },
        }
    )


@router.get("/region-heat")
def dashboard_region_heat(
    variety_id: int | None = Query(default=None, description="品种ID，缺省取排序第一的在用品种"),
    on_date: str | None = Query(default=None, alias="date", description="日期 YYYY-MM-DD"),
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """区域热力：各地区当日均价、同比与等级。"""
    if variety_id is None:
        variety_id = db.execute(
            select(Variety.id).order_by(Variety.sort, Variety.id)
        ).scalars().first()
    if variety_id is None:
        return ok([])
    pricing.get_variety(db, variety_id)
    anchor = pricing.parse_date(on_date) or pricing.latest_price_date(
        db, variety_id=variety_id
    )
    if not anchor:
        return ok([])

    price_rows = db.execute(
        select(PriceRecord.region_id, func.avg(PriceRecord.price))
        .where(PriceRecord.variety_id == int(variety_id), PriceRecord.price_date == anchor)
        .group_by(PriceRecord.region_id)
    ).all()
    price_map = {int(row[0]): float(row[1]) for row in price_rows if row[1] is not None}

    # 同比优先取特征表中不晚于当日的最近一次计算值
    feature_date = db.execute(
        select(func.max(FeatureRecord.calc_date)).where(
            FeatureRecord.variety_id == int(variety_id),
            FeatureRecord.calc_date <= anchor,
        )
    ).scalar()
    yoy_map: dict[int, float] = {}
    if feature_date:
        rows = db.execute(
            select(FeatureRecord.region_id, func.avg(FeatureRecord.yoy_pct)).where(
                FeatureRecord.variety_id == int(variety_id),
                FeatureRecord.calc_date == feature_date,
            ).group_by(FeatureRecord.region_id)
        ).all()
        yoy_map = {int(row[0]): float(row[1]) for row in rows if row[1] is not None}

    regions = db.execute(select(Region).order_by(Region.sort, Region.id)).scalars().all()
    items = []
    for region in regions:
        price = price_map.get(region.id)
        yoy = yoy_map.get(region.id)
        if yoy is None and price is not None:
            base = pricing.price_one_year_ago(
                db, variety_id=variety_id, region_id=region.id, anchor=anchor
            )
            yoy = pricing.pct_change(price, base)
        items.append(
            {
                "region_code": region.code,
                "region": region.name,
                "price": pricing.r2(price) if price is not None else None,
                "yoy_pct": pricing.r2(yoy) if yoy is not None else 0.0,
                "level": pricing.level_of(yoy),
            }
        )
    return ok(items)


@router.get("/category-share")
def dashboard_category_share(
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """品类占比：按品类统计记录数占比与均价。"""
    rows = db.execute(
        select(
            Variety.category,
            func.count(PriceRecord.id),
            func.avg(PriceRecord.price),
        )
        .join(Variety, Variety.id == PriceRecord.variety_id)
        .group_by(Variety.category)
        .order_by(func.count(PriceRecord.id).desc())
    ).all()
    total = sum(int(row[1]) for row in rows) or 1
    items = [
        {
            "category": row[0],
            "value": round(int(row[1]) / total * 100, 2),
            "record_count": int(row[1]),
            "avg_price": pricing.r2(row[2]) or 0.0,
        }
        for row in rows
    ]
    return ok(items)


@router.get("/alerts/latest")
def dashboard_latest_alerts(
    limit: int = Query(default=6, ge=1, le=50),
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """最新预警摘要。"""
    rows = db.execute(
        select(AlertRecord, Variety.name, Region.name)
        .join(Variety, Variety.id == AlertRecord.variety_id)
        .join(Region, Region.id == AlertRecord.region_id)
        .order_by(AlertRecord.alert_date.desc(), AlertRecord.id.desc())
        .limit(limit)
    ).all()
    return ok(
        [
            {
                "id": record.id,
                "level": record.level,
                "title": record.title,
                "variety": variety_name,
                "region": region_name,
                "alert_date": _fmt_date(record.alert_date),
                "status": record.status,
            }
            for record, variety_name, region_name in rows
        ]
    )


@router.get("/forecast-brief")
def dashboard_forecast_brief(
    limit: int = Query(default=5, ge=1, le=50),
    _perm: object = Depends(require_permission("dashboard:view")),
    db: Session = Depends(get_db),
):
    """最新预测摘要（方向/区间）。"""
    rows = db.execute(
        select(ForecastResult, Variety.name, Region.name)
        .join(Variety, Variety.id == ForecastResult.variety_id)
        .join(Region, Region.id == ForecastResult.region_id)
        .order_by(ForecastResult.created_at.desc(), ForecastResult.id.desc())
        .limit(limit)
    ).all()
    return ok(
        [
            {
                "variety_id": record.variety_id,
                "variety": variety_name,
                "region": region_name,
                "horizon": record.horizon,
                "point": pricing.r2(record.point),
                "change_pct": pricing.r2(record.expected_change_pct),
                "direction": record.direction,
                "confidence": pricing.r2(record.confidence),
                "forecast_date": _fmt_date(record.target_date or record.forecast_date),
                "generated_at": _fmt_time(record.created_at),
            }
            for record, variety_name, region_name in rows
        ]
    )
