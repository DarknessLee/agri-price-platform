"""数据质量服务：完整率测算、异常分布统计、质量问题登记与查询。

口径：
- 完整率 = 近 30 天已覆盖的（品种×地区×市场类型×日期）单元格 / 应有单元格；
- 重复率按唯一约束（品种/市场/日期/市场类型）分组测算，入库层面已由唯一约束兜底；
- 异常以 quality_issue 表记录，状态分「待处理 / 已处理 / 已排除」。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FeatureRecord, PriceRecord, QualityIssue, Variety
from ..database import now

WINDOW_DAYS = 30
# 与种子数据 / 导入流程统一的问题分类
ISSUE_TYPES = ("价格异常波动", "数据缺失估算", "重复记录", "格式错误")
# 兼容历史词表（早期版本使用「异常值」「缺失」「重复」）
_OUTLIER_TYPES = ("价格异常波动", "异常值")
_MISSING_TYPES = ("数据缺失估算", "缺失")
_DUPLICATE_TYPES = ("重复记录", "重复")
_FORMAT_TYPES = ("格式错误",)


def _category(issue_type: str | None) -> str:
    """把问题类型归一到四类之一，未知类型归为价格异常波动。"""
    if issue_type in _MISSING_TYPES:
        return "数据缺失估算"
    if issue_type in _DUPLICATE_TYPES:
        return "重复记录"
    if issue_type in _FORMAT_TYPES:
        return "格式错误"
    return "价格异常波动"


_TYPE_SYNONYMS = {
    "价格异常波动": ("价格异常波动", "异常值"),
    "数据缺失估算": ("数据缺失估算", "缺失"),
    "重复记录": ("重复记录", "重复"),
    "格式错误": ("格式错误",),
}


def types_for(issue_type: str) -> tuple[str, ...]:
    """返回某分类在库中可能出现的全部历史写法，用于筛选。"""
    return _TYPE_SYNONYMS[_category(issue_type)]


def parse_date(value, field: str = "日期") -> date | None:
    """解析查询用日期；空值返回 None，非法格式抛 E4001。"""
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
    from ..security import ApiError

    raise ApiError("E4001", f"{field}格式不正确，应为 YYYY-MM-DD")


def _fmt_time(value) -> str | None:
    """日期时间转契约格式。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return None


def window_bounds(db: Session, days: int = WINDOW_DAYS) -> tuple[date, date]:
    """质量统计窗口：以最新价格日为锚点的最近 N 天（无数据时用今天）。"""
    days = max(1, int(days or WINDOW_DAYS))
    anchor = db.execute(select(func.max(PriceRecord.price_date))).scalar() or date.today()
    return anchor - timedelta(days=days - 1), anchor


def _combos(db: Session, variety_id: int | None = None) -> set[tuple[int, int, str]]:
    """已出现过的（品种, 地区, 市场类型）组合，作为完整率的应有口径。"""
    stmt = select(PriceRecord.variety_id, PriceRecord.region_id, PriceRecord.market_type).distinct()
    if variety_id:
        stmt = stmt.where(PriceRecord.variety_id == int(variety_id))
    return {(int(row[0]), int(row[1]), row[2]) for row in db.execute(stmt).all()}


def _present_cells(
    db: Session, start: date, end: date, variety_id: int | None = None
) -> int:
    """窗口内已覆盖的单元格数量（去重后的 品种×地区×市场类型×日期）。"""
    stmt = (
        select(
            PriceRecord.price_date,
            PriceRecord.variety_id,
            PriceRecord.region_id,
            PriceRecord.market_type,
        )
        .where(PriceRecord.price_date >= start, PriceRecord.price_date <= end)
        .distinct()
    )
    if variety_id:
        stmt = stmt.where(PriceRecord.variety_id == int(variety_id))
    return len(db.execute(stmt).all())


def completeness(db: Session, days: int = WINDOW_DAYS, variety_id: int | None = None) -> float:
    """完整率（百分数，2 位小数）；无数据返回 0。"""
    combos = _combos(db, variety_id=variety_id)
    if not combos:
        return 0.0
    days = max(1, int(days or WINDOW_DAYS))
    start, end = window_bounds(db, days)
    expected = len(combos) * days
    present = _present_cells(db, start, end, variety_id=variety_id)
    if expected <= 0:
        return 0.0
    return round(min(present, expected) / expected * 100, 2)


def _pending_count(
    db: Session, issue_types: str | tuple[str, ...], variety_id: int | None = None
) -> int:
    """某类型（可传多套词表）待处理问题数。"""
    types = (issue_types,) if isinstance(issue_types, str) else tuple(issue_types)
    stmt = select(func.count(QualityIssue.id)).where(
        QualityIssue.issue_type.in_(types),
        QualityIssue.status == "待处理",
    )
    if variety_id:
        stmt = stmt.where(QualityIssue.variety_id == int(variety_id))
    return int(db.execute(stmt).scalar() or 0)


def issue_type_distribution(db: Session) -> list[dict]:
    """按问题类型的数量分布（归一为四类，含已处理，便于看历史）。"""
    rows = db.execute(
        select(QualityIssue.issue_type, func.count(QualityIssue.id)).group_by(
            QualityIssue.issue_type
        )
    ).all()
    counts: dict[str, int] = {}
    for issue_type, count in rows:
        counts[_category(issue_type)] = counts.get(_category(issue_type), 0) + int(count)
    return [{"type": name, "count": counts.get(name, 0)} for name in ISSUE_TYPES]


def duplicate_rate(db: Session) -> float:
    """重复率（百分数）：按唯一键分组统计重复组的额外行数。"""
    total = int(db.execute(select(func.count(PriceRecord.id))).scalar() or 0)
    if total <= 0:
        return 0.0
    grouped = (
        select(func.count().label("cnt"))
        .select_from(PriceRecord)
        .group_by(
            PriceRecord.variety_id,
            PriceRecord.market_id,
            PriceRecord.price_date,
            PriceRecord.market_type,
        )
        .having(func.count() > 1)
        .subquery()
    )
    duplicate_rows = int(db.execute(select(func.sum(grouped.c.cnt))).scalar() or 0)
    # 每个重复组有 cnt 行，其中 1 行为有效，其余为重复
    groups = int(db.execute(select(func.count()).select_from(grouped)).scalar() or 0)
    duplicates = max(duplicate_rows - groups, 0)
    return round(duplicates / total * 100, 2)


def summary(db: Session) -> dict:
    """质量汇总：完整率、重复率、异常数、缺失数、按品种明细。"""
    start, end = window_bounds(db)
    total_records = int(db.execute(select(func.count(PriceRecord.id))).scalar() or 0)
    combos = _combos(db)
    expected = len(combos) * WINDOW_DAYS
    present = _present_cells(db, start, end) if combos else 0
    overall = round(min(present, expected) / expected * 100, 2) if expected else 0.0

    varieties = db.execute(select(Variety).order_by(Variety.sort, Variety.id)).scalars().all()
    by_variety = [
        {
            "variety": variety.name,
            "completeness": completeness(db, WINDOW_DAYS, variety.id),
            "outliers": _pending_count(db, _OUTLIER_TYPES, variety.id),
        }
        for variety in varieties
    ]

    updated_at = db.execute(select(func.max(PriceRecord.created_at))).scalar()
    if not isinstance(updated_at, datetime):
        updated_at = db.execute(select(func.max(QualityIssue.resolved_at))).scalar()
    if not isinstance(updated_at, datetime):
        updated_at = now()

    return {
        "completeness": overall,
        "duplicate_rate": duplicate_rate(db),
        "outlier_count": _pending_count(db, _OUTLIER_TYPES),
        "total_records": total_records,
        "missing_count": max(expected - present, 0) if combos else 0,
        "by_variety": by_variety,
        "by_type": issue_type_distribution(db),
        "updated_at": _fmt_time(updated_at) or _fmt_time(now()),
        "window": {"start": _fmt_time(start), "end": _fmt_time(end), "days": WINDOW_DAYS},
    }


def record_issue(
    db: Session,
    *,
    variety_id: int,
    region_id: int,
    issue_date: date,
    issue_type: str,
    detail: str,
    price_id: int = 0,
) -> QualityIssue:
    """登记一条质量问题（由数据导入等写操作调用，不提交事务）。"""
    issue = QualityIssue(
        price_id=price_id or 0,
        variety_id=int(variety_id),
        region_id=int(region_id),
        issue_date=issue_date,
        issue_type=_category(issue_type),
        detail=(detail or "")[:250],
        status="待处理",
    )
    db.add(issue)
    return issue


def issue_rows(db: Session, issues: list[QualityIssue]) -> list[dict]:
    """把质量问题对象序列化为契约结构（附品种/地区名称）。"""
    if not issues:
        return []
    variety_names = {
        row[0]: row[1] for row in db.execute(select(Variety.id, Variety.name)).all()
    }
    from ..models import Region

    region_names = {
        row[0]: row[1] for row in db.execute(select(Region.id, Region.name)).all()
    }
    prices: dict[int, float] = {}
    price_ids = [issue.price_id for issue in issues if issue.price_id]
    if price_ids:
        rows = db.execute(
            select(PriceRecord.id, PriceRecord.price).where(PriceRecord.id.in_(price_ids))
        ).all()
        prices = {int(row[0]): float(row[1]) for row in rows if row[1] is not None}
    return [
        {
            "id": issue.id,
            "date": _fmt_time(issue.issue_date),
            "variety": variety_names.get(issue.variety_id, ""),
            "region": region_names.get(issue.region_id, ""),
            "price": prices.get(issue.price_id),
            "issue_type": issue.issue_type,
            "detail": issue.detail,
            "status": issue.status,
        }
        for issue in issues
    ]
