"""价格数据服务：序列查询与粒度聚合、统计指标、区域价差、品种比价、季节指数。

约定：
- 只读，不产生任何写操作；
- 无数据时返回空列表 / 零值，不抛异常；
- 价格保留 2 位小数，比率为百分数数值（2.35 表示 2.35%）；
- 日期统一使用 ``YYYY-MM-DD`` 字符串出入参。
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FeatureRecord, Market, PriceRecord, Region, Variety
from ..security import ApiError

# 数据口径：批发 / 零售 / 产地
MARKET_TYPES = ("批发", "零售", "产地")
GRANULARITY_LABELS = {"day": "日", "week": "周", "month": "月"}
_GRANULARITY_ALIASES = {
    "day": "day",
    "d": "day",
    "日": "day",
    "week": "week",
    "w": "week",
    "周": "week",
    "month": "month",
    "m": "month",
    "月": "month",
}
DEFAULT_UNIT = "元/公斤"


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

def r2(value) -> float | None:
    """四舍五入到 2 位小数；None 原样返回。"""
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def parse_date(value, field: str = "日期") -> date | None:
    """解析 ``YYYY-MM-DD`` / ``YYYY/MM/DD`` / ``YYYYMMDD``；空值返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ApiError("E4001", f"{field}格式不正确，应为 YYYY-MM-DD")


def parse_range(start, end) -> tuple[date | None, date | None]:
    """解析查询区间并校验先后顺序。"""
    start_date = parse_date(start, "开始日期")
    end_date = parse_date(end, "结束日期")
    if start_date and end_date and start_date > end_date:
        raise ApiError("E4001", "开始日期不能晚于结束日期")
    return start_date, end_date


def normalize_granularity(value: str | None) -> str:
    """粒度归一化：仅支持 day / week / month。"""
    key = str(value or "day").strip().lower()
    key = _GRANULARITY_ALIASES.get(key, key)
    if key not in GRANULARITY_LABELS:
        raise ApiError("E4001", "粒度仅支持 day、week、month")
    return key


def period_key(day: date, granularity: str) -> date:
    """把日频日期映射为聚合周期的起始日。"""
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def get_variety(db: Session, variety_id: int | None) -> Variety:
    """按主键取品种，不存在时返回 404 业务异常。"""
    variety = db.get(Variety, int(variety_id)) if variety_id else None
    if not variety:
        raise ApiError("E4040", "品种不存在", 404)
    return variety


def get_region(db: Session, region_id: int | None) -> Region:
    """按主键取地区，不存在时返回 404 业务异常。"""
    region = db.get(Region, int(region_id)) if region_id else None
    if not region:
        raise ApiError("E4040", "地区不存在", 404)
    return region


def variety_unit(db: Session, variety_id: int | None) -> str:
    """取品种计价单位，缺失时回退默认单位。"""
    if variety_id:
        variety = db.get(Variety, int(variety_id))
        if variety and variety.unit:
            return variety.unit
    return DEFAULT_UNIT


def pct_change(latest, base) -> float | None:
    """计算涨跌幅（百分数）；基数为 0 / 空时返回 None。"""
    if latest is None or base is None or not base:
        return None
    try:
        return round((float(latest) - float(base)) / float(base) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def volatility(values: Sequence[float]) -> float:
    """日环比波动的标准差（百分数），用于 30 日波动率。"""
    changes: list[float] = []
    for prev, cur in zip(values, values[1:]):
        if prev:
            changes.append((float(cur) - float(prev)) / float(prev) * 100)
    if len(changes) < 2:
        return 0.0
    return round(statistics.stdev(changes), 2)


def level_of(yoy_pct: float | None) -> str:
    """按同比幅度给出等级标签（用于区域热力/联动展示）。"""
    if yoy_pct is None:
        return "低"
    value = abs(float(yoy_pct))
    if value >= 8:
        return "高"
    if value >= 3:
        return "中"
    return "低"


# --------------------------------------------------------------------------- #
# 基础查询
# --------------------------------------------------------------------------- #

def _conditions(
    *,
    variety_id: int | None = None,
    region_id: int | None = None,
    market_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list:
    """构造价格事实表的通用过滤条件。"""
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


def latest_price_date(
    db: Session,
    *,
    variety_id: int | None = None,
    region_id: int | None = None,
    market_type: str | None = None,
) -> date | None:
    """取满足条件的最近价格日期；无数据返回 None。"""
    conds = _conditions(variety_id=variety_id, region_id=region_id, market_type=market_type)
    return db.execute(select(func.max(PriceRecord.price_date)).where(*conds)).scalar()


def daily_points(
    db: Session,
    *,
    variety_id: int | None = None,
    region_id: int | None = None,
    market_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[date, float]]:
    """按日聚合平均价（跨市场/市场类型求均值），升序返回 (日期, 均价)。"""
    conds = _conditions(
        variety_id=variety_id, region_id=region_id, market_type=market_type, start=start, end=end
    )
    stmt = (
        select(PriceRecord.price_date, func.avg(PriceRecord.price))
        .where(*conds)
        .group_by(PriceRecord.price_date)
        .order_by(PriceRecord.price_date)
    )
    rows = db.execute(stmt).all()
    return [(row[0], float(row[1])) for row in rows if row[1] is not None]


def daily_mean_by_variety(
    db: Session,
    *,
    region_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
) -> tuple[list[date], dict[int, dict[date, float]]]:
    """按品种×日聚合均价，返回 (日期列表, {品种ID: {日期: 均价}})。"""
    conds = _conditions(region_id=region_id, start=start, end=end)
    stmt = (
        select(PriceRecord.variety_id, PriceRecord.price_date, func.avg(PriceRecord.price))
        .where(*conds)
        .group_by(PriceRecord.variety_id, PriceRecord.price_date)
        .order_by(PriceRecord.price_date)
    )
    dates: set[date] = set()
    matrix: dict[int, dict[date, float]] = {}
    for variety_id, price_date, price in db.execute(stmt).all():
        if price is None:
            continue
        dates.add(price_date)
        matrix.setdefault(int(variety_id), {})[price_date] = float(price)
    return sorted(dates), matrix


def feature_snapshot(
    db: Session,
    *,
    variety_id: int,
    region_id: int | None = None,
    on_date: date | None = None,
) -> dict:
    """取特征表快照（默认最新日期，按品种/地区求均值）。无数据返回空 dict。"""
    conds = [FeatureRecord.variety_id == int(variety_id)]
    if region_id:
        conds.append(FeatureRecord.region_id == int(region_id))
    target = on_date or db.execute(
        select(func.max(FeatureRecord.calc_date)).where(*conds)
    ).scalar()
    if not target:
        return {}
    conds.append(FeatureRecord.calc_date == target)
    row = db.execute(
        select(
            func.avg(FeatureRecord.yoy_pct),
            func.avg(FeatureRecord.mom_pct),
            func.avg(FeatureRecord.volatility_30d),
            func.avg(FeatureRecord.seasonal_index),
            func.avg(FeatureRecord.cost_index),
            func.avg(FeatureRecord.freight_index),
            func.avg(FeatureRecord.weather_score),
            func.avg(FeatureRecord.futures_price),
            func.max(FeatureRecord.holiday_flag),
        ).where(*conds)
    ).first()
    if not row:
        return {}
    keys = (
        "yoy_pct",
        "mom_pct",
        "volatility_30d",
        "seasonal_index",
        "cost_index",
        "freight_index",
        "weather_score",
        "futures_price",
        "holiday_flag",
    )
    snapshot: dict = {"date": target.strftime("%Y-%m-%d")}
    for key, value in zip(keys, row):
        if value is None:
            snapshot[key] = None
        elif key == "holiday_flag":
            snapshot[key] = int(value)
        else:
            snapshot[key] = r2(value)
    return snapshot


# --------------------------------------------------------------------------- #
# 序列 / 统计
# --------------------------------------------------------------------------- #

def series_data(
    db: Session,
    *,
    variety_id: int,
    region_id: int | None = None,
    market_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
    granularity: str = "day",
) -> dict:
    """价格序列：按粒度聚合，未指定市场类型时按市场类型拆多条序列。"""
    granularity = normalize_granularity(granularity)
    get_variety(db, variety_id)
    if not start and not end:
        # 未指定区间时默认取最近 365 天，避免一次返回全部历史
        anchor = latest_price_date(
            db, variety_id=variety_id, region_id=region_id, market_type=market_type
        ) or date.today()
        end = anchor
        start = anchor - timedelta(days=365)
    conds = _conditions(
        variety_id=variety_id, region_id=region_id, market_type=market_type, start=start, end=end
    )
    rows = db.execute(
        select(PriceRecord.price_date, PriceRecord.market_type, PriceRecord.price)
        .where(*conds)
        .order_by(PriceRecord.price_date)
    ).all()

    buckets: dict[date, dict[str, list[float]]] = {}
    for price_date, row_market_type, price in rows:
        if price is None:
            continue
        key = period_key(price_date, granularity)
        buckets.setdefault(key, {}).setdefault(row_market_type or "批发", []).append(float(price))

    dates = sorted(buckets)
    if market_type:
        types = [market_type]
    else:
        types = [mt for mt in MARKET_TYPES if any(mt in bucket for bucket in buckets.values())]
        if not types:  # 兜底：使用数据里出现的市场类型
            types = sorted({mt for bucket in buckets.values() for mt in bucket})
    series = []
    for mt in types:
        values = []
        for day in dates:
            prices = buckets[day].get(mt) or []
            values.append(r2(statistics.fmean(prices)) if prices else None)
        series.append({"name": f"{mt}均价", "values": values})
    return {
        "dates": [day.strftime("%Y-%m-%d") for day in dates],
        "series": series,
        "unit": variety_unit(db, variety_id),
        "granularity": granularity,
    }


def price_stats(
    db: Session,
    *,
    variety_id: int,
    region_id: int | None = None,
    days: int = 90,
) -> dict:
    """区间统计：均价、最高/最低、最新/上期、同比环比、波动率、中位数、记录数。"""
    get_variety(db, variety_id)
    days = max(1, int(days or 90))
    anchor = latest_price_date(db, variety_id=variety_id, region_id=region_id) or date.today()
    start = anchor - timedelta(days=days - 1)
    points = daily_points(
        db, variety_id=variety_id, region_id=region_id, start=start, end=anchor
    )
    conds = _conditions(variety_id=variety_id, region_id=region_id, start=start, end=anchor)
    records = db.execute(
        select(func.count(PriceRecord.id)).where(*conds)
    ).scalar() or 0
    updated_at = db.execute(
        select(func.max(PriceRecord.created_at)).where(*conds)
    ).scalar()
    empty = {
        "avg": 0.0,
        "max": 0.0,
        "min": 0.0,
        "latest": 0.0,
        "prev": 0.0,
        "yoy_pct": 0.0,
        "mom_pct": 0.0,
        "volatility": 0.0,
        "median": 0.0,
        "records": 0,
        "updated_at": updated_at.strftime("%Y-%m-%dT%H:%M:%S") if updated_at else None,
    }
    if not points:
        return empty

    values = [price for _, price in points]
    latest = values[-1]
    prev = values[-2] if len(values) > 1 else None
    stats = {
        "avg": r2(statistics.fmean(values)),
        "max": r2(max(values)),
        "min": r2(min(values)),
        "latest": r2(latest),
        "prev": r2(prev),
        "median": r2(statistics.median(values)),
        "volatility": volatility(values[-31:]),
        "records": int(records),
        "updated_at": updated_at.strftime("%Y-%m-%dT%H:%M:%S") if updated_at else None,
        "mom_pct": pct_change(latest, prev),
        "yoy_pct": None,
    }
    # 同比：优先使用特征表口径，缺失时按一年前价格回算
    snapshot = feature_snapshot(db, variety_id=variety_id, region_id=region_id)
    yoy = snapshot.get("yoy_pct")
    if yoy is None:
        base = price_one_year_ago(
            db, variety_id=variety_id, region_id=region_id, anchor=anchor
        )
        yoy = pct_change(latest, base)
    stats["yoy_pct"] = 0.0 if yoy is None else r2(yoy)
    if stats["mom_pct"] is None:
        stats["mom_pct"] = 0.0
    return stats


def price_one_year_ago(
    db: Session,
    *,
    variety_id: int,
    region_id: int | None,
    anchor: date,
) -> float | None:
    """取一年前附近（±35 天窗口内最接近）的均价，用于同比回算。"""
    target = anchor - timedelta(days=365)
    points = daily_points(
        db,
        variety_id=variety_id,
        region_id=region_id,
        start=target - timedelta(days=35),
        end=target + timedelta(days=35),
    )
    if not points:
        return None
    nearest = min(points, key=lambda item: abs((item[0] - target).days))
    return nearest[1]


def region_spread(db: Session, *, variety_id: int, days: int = 30) -> dict:
    """区域比价：各地区日度均价序列 + 区间统计（均价/极值/区间价差）。"""
    variety = get_variety(db, variety_id)
    days = max(1, int(days or 30))
    anchor = latest_price_date(db, variety_id=variety_id) or date.today()
    start = anchor - timedelta(days=days - 1)
    regions = db.execute(select(Region).order_by(Region.sort, Region.id)).scalars().all()
    stmt = (
        select(Region.id, Region.name, PriceRecord.price_date, func.avg(PriceRecord.price))
        .join(Region, Region.id == PriceRecord.region_id)
        .where(PriceRecord.variety_id == variety.id, PriceRecord.price_date >= start,
               PriceRecord.price_date <= anchor)
        .group_by(Region.id, Region.name, PriceRecord.price_date)
        .order_by(PriceRecord.price_date)
    )
    rows = db.execute(stmt).all()
    dates = sorted({row[2] for row in rows})
    data: dict[int, dict[date, float]] = {}
    names: dict[int, str] = {}
    for region_id, region_name, price_date, price in rows:
        names[int(region_id)] = region_name
        data.setdefault(int(region_id), {})[price_date] = float(price)

    # 按地区排序输出（无数据的地区也占位，前端图例稳定）
    ordered_ids = [region.id for region in regions if region.id in names]
    series = [
        {
            "region": names[region_id],
            "values": [r2(data[region_id].get(day)) for day in dates],
        }
        for region_id in ordered_ids
    ]
    stats = []
    for region_id in ordered_ids:
        values = list(data[region_id].values())
        stats.append(
            {
                "region": names[region_id],
                "avg": r2(statistics.fmean(values)),
                "min": r2(min(values)),
                "max": r2(max(values)),
                "spread": r2(max(values) - min(values)),
            }
        )
    averages = [item["avg"] for item in stats if item["avg"] is not None]
    overall = r2(max(averages) - min(averages)) if len(averages) >= 2 else 0.0
    return {
        "dates": [day.strftime("%Y-%m-%d") for day in dates],
        "series": series,
        "stats": stats,
        "unit": variety.unit or DEFAULT_UNIT,
        "overall_spread": overall,
    }


def variety_compare(db: Session, *, region_id: int | None = None, days: int = 90) -> dict:
    """品种间比价：以区间首个有效日为 100 归一化的价格指数。"""
    days = max(1, int(days or 90))
    anchor = latest_price_date(db, region_id=region_id) or date.today()
    start = anchor - timedelta(days=days - 1)
    dates, matrix = daily_mean_by_variety(db, region_id=region_id, start=start, end=anchor)
    varieties = db.execute(select(Variety).order_by(Variety.sort, Variety.id)).scalars().all()
    series = []
    for variety in varieties:
        price_map = matrix.get(variety.id) or {}
        if not price_map:
            continue
        base_day = min(price_map)
        base_price = price_map[base_day]
        if not base_price:
            continue
        values = []
        for day in dates:
            price = price_map.get(day)
            values.append(r2(price / base_price * 100) if price else None)
        series.append({"name": variety.name, "values": values})
    return {
        "dates": [day.strftime("%Y-%m-%d") for day in dates],
        "series": series,
        "normalized": True,
    }


def seasonality(
    db: Session, *, variety_id: int, region_id: int | None = None, years: int = 3
) -> dict:
    """季节指数：优先用特征表 seasonal_index，缺失时按月度均价相对全年均值测算。"""
    get_variety(db, variety_id)
    years = max(1, int(years or 3))
    anchor = latest_price_date(db, variety_id=variety_id, region_id=region_id) or date.today()
    start = anchor.replace(year=anchor.year - years + 1, month=1, day=1) if anchor.year - years + 1 >= 1 else anchor
    conds = [FeatureRecord.variety_id == int(variety_id), FeatureRecord.calc_date >= start]
    if region_id:
        conds.append(FeatureRecord.region_id == int(region_id))
    feature_rows = db.execute(
        select(FeatureRecord.calc_date, FeatureRecord.seasonal_index).where(*conds)
    ).all()

    monthly: dict[int, list[float]] = {month: [] for month in range(1, 13)}
    source = "特征表"
    if feature_rows:
        for calc_date, index in feature_rows:
            if index is not None:
                monthly[calc_date.month].append(float(index))
    else:
        source = "价格测算"
        points = daily_points(
            db,
            variety_id=variety_id,
            region_id=region_id,
            start=start,
            end=anchor,
        )
        month_prices: dict[int, list[float]] = {month: [] for month in range(1, 13)}
        for price_date, price in points:
            month_prices[price_date.month].append(price)
        month_avg = {
            month: statistics.fmean(values) for month, values in month_prices.items() if values
        }
        if month_avg:
            overall = statistics.fmean(month_avg.values())
            for month, avg in month_avg.items():
                monthly[month] = [avg / overall * 100] if overall else []
    indices = [r2(statistics.fmean(monthly[month])) if monthly[month] else None for month in range(1, 13)]
    return {
        "months": list(range(1, 13)),
        "indices": indices,
        "unit": "季节指数",
        "source": source,
        "unit_price": variety_unit(db, variety_id),
    }
