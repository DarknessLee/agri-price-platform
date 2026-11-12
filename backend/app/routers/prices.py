"""价格监测接口（契约 §4）：分页列表、序列、统计、区域价差、品种比价、季节指数、CSV 导出。"""
from __future__ import annotations

import csv
import io
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Market, PriceRecord, Region, Variety
from ..responses import ok, page_args, paged
from ..security import ApiError, client_ip, require_permission
from ..services import pricing

router = APIRouter(prefix="/prices", tags=["价格监测"])

MARKET_TYPES = ("批发", "零售")
EXPORT_LIMIT = 100_000


def _filters(
    *,
    variety_id: int | None,
    region_id: int | None,
    market_type: str | None,
    start: date | None,
    end: date | None,
) -> list:
    """构造价格记录过滤条件。"""
    conds = []
    if variety_id:
        conds.append(PriceRecord.variety_id == int(variety_id))
    if region_id:
        conds.append(PriceRecord.region_id == int(region_id))
    if market_type:
        conds.append(PriceRecord.market_type == market_type)
    if start:
        conds.append(PriceRecord.price_date >= start)
    if end:
        conds.append(PriceRecord.price_date <= end)
    return conds


def _check_type(market_type: str | None) -> str | None:
    """校验市场类型取值。"""
    if market_type and market_type not in MARKET_TYPES:
        raise ApiError("E4001", "市场类型仅支持批发、零售")
    return market_type


def _fmt(value) -> str | None:
    """日期格式化。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _row_item(row) -> dict:
    """价格记录 + 维度名称 -> 契约列表项。"""
    record: PriceRecord = row[0]
    return {
        "id": record.id,
        "date": _fmt(record.price_date),
        "variety": row[1],
        "region": row[2],
        "market": row[3],
        "market_type": record.market_type,
        "price": pricing.r2(record.price),
        "min_price": pricing.r2(record.min_price),
        "max_price": pricing.r2(record.max_price),
        "volume": pricing.r2(record.volume),
        "unit": record.unit,
        "quality_flag": record.quality_flag,
    }


@router.get("")
def list_prices(
    variety_id: int | None = Query(default=None, description="品种ID"),
    region_id: int | None = Query(default=None, description="地区ID"),
    market_type: str | None = Query(default=None, description="市场类型：批发/零售"),
    start: str | None = Query(default=None, description="开始日期 YYYY-MM-DD"),
    end: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """价格记录分页列表。"""
    page, page_size = page_args(page, page_size)
    start_date, end_date = pricing.parse_range(start, end)
    market_type = _check_type(market_type)
    conds = _filters(
        variety_id=variety_id,
        region_id=region_id,
        market_type=market_type,
        start=start_date,
        end=end_date,
    )
    total = int(db.execute(select(func.count(PriceRecord.id)).where(*conds)).scalar() or 0)
    stmt = (
        select(PriceRecord, Variety.name, Region.name, Market.name)
        .join(Variety, Variety.id == PriceRecord.variety_id)
        .join(Region, Region.id == PriceRecord.region_id)
        .join(Market, Market.id == PriceRecord.market_id)
        .where(*conds)
        .order_by(PriceRecord.price_date.desc(), PriceRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(stmt).all()
    return paged([_row_item(row) for row in rows], total, page, page_size)


@router.get("/series")
def price_series(
    variety_id: int = Query(..., description="品种ID"),
    region_id: int | None = Query(default=None),
    market_type: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    granularity: str = Query(default="day", description="粒度：day/week/month"),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """价格序列（日/周/月聚合）。"""
    start_date, end_date = pricing.parse_range(start, end)
    data = pricing.series_data(
        db,
        variety_id=variety_id,
        region_id=region_id,
        market_type=_check_type(market_type),
        start=start_date,
        end=end_date,
        granularity=granularity,
    )
    return ok(data)


@router.get("/stats")
def price_stats(
    variety_id: int = Query(..., description="品种ID"),
    region_id: int | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=3650),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """区间价格统计指标。"""
    return ok(pricing.price_stats(db, variety_id=variety_id, region_id=region_id, days=days))


@router.get("/region-spread")
def region_spread(
    variety_id: int = Query(..., description="品种ID"),
    days: int = Query(default=30, ge=1, le=3650),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """区域比价与价差。"""
    return ok(pricing.region_spread(db, variety_id=variety_id, days=days))


@router.get("/variety-compare")
def variety_compare(
    region_id: int | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=3650),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """品种间比价（区间首日归一化为 100）。"""
    return ok(pricing.variety_compare(db, region_id=region_id, days=days))


@router.get("/seasonality")
def seasonality(
    variety_id: int = Query(..., description="品种ID"),
    region_id: int | None = Query(default=None),
    years: int = Query(default=3, ge=1, le=10),
    _perm: object = Depends(require_permission("monitor:view")),
    db: Session = Depends(get_db),
):
    """季节指数（1-12 月）。"""
    return ok(pricing.seasonality(db, variety_id=variety_id, region_id=region_id, years=years))


@router.get("/export")
def export_prices(
    variety_id: int | None = Query(default=None),
    region_id: int | None = Query(default=None),
    market_type: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    _perm: object = Depends(require_permission("monitor:export")),
    db: Session = Depends(get_db),
):
    """按当前筛选条件导出 CSV（UTF-8 BOM，Excel 直接可读）。"""
    start_date, end_date = pricing.parse_range(start, end)
    market_type = _check_type(market_type)
    conds = _filters(
        variety_id=variety_id,
        region_id=region_id,
        market_type=market_type,
        start=start_date,
        end=end_date,
    )
    stmt = (
        select(
            PriceRecord.price_date,
            Variety.name,
            Region.name,
            Market.name,
            PriceRecord.market_type,
            PriceRecord.price,
            PriceRecord.min_price,
            PriceRecord.max_price,
            PriceRecord.volume,
            PriceRecord.unit,
            PriceRecord.quality_flag,
        )
        .join(Variety, Variety.id == PriceRecord.variety_id)
        .join(Region, Region.id == PriceRecord.region_id)
        .join(Market, Market.id == PriceRecord.market_id)
        .where(*conds)
        .order_by(PriceRecord.price_date.desc(), PriceRecord.id.desc())
        .limit(EXPORT_LIMIT)
    )
    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM：避免 Excel 打开中文乱码
    writer = csv.writer(buffer)
    writer.writerow(
        ["日期", "品种", "地区", "市场", "市场类型", "价格(元/公斤)", "最低价", "最高价", "成交量", "单位", "数据质量"]
    )
    for row in db.execute(stmt):
        writer.writerow(
            [
                _fmt(row[0]),
                row[1],
                row[2],
                row[3],
                row[4],
                pricing.r2(row[5]),
                pricing.r2(row[6]),
                pricing.r2(row[7]),
                pricing.r2(row[8]),
                row[9],
                row[10],
            ]
        )
    content = buffer.getvalue().encode("utf-8")
    filename = f"价格监测数据_{date.today():%Y%m%d}.csv"
    headers = {
        "Content-Disposition": (
            f"attachment; filename=price_export_{date.today():%Y%m%d}.csv; "
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)
