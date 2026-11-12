"""预警服务：规则扫描、预警生成、统计与处置。

规则类型（契约 §7）：
- price_threshold  价格阈值：批发价与阈值比较（gt/lt/gte/lte/abs_gt）
- volatility       波动率异常：FeatureRecord.volatility_30d 与阈值比较（常用 abs_gt）
- yoy              同比异常：FeatureRecord.yoy_pct 与阈值比较（常用 abs_gt）
- spread           区域价差：同品种跨地区最高价与最低价之差超过阈值（gt）

evaluate_rules(db, days=30) 扫描窗口内每个日频价格点，命中即写 AlertRecord（按
rule_id + variety_id + region_id + alert_date 去重）；同一规则组合 7 天内最多保留
2 条预警，避免阈值持续越界时产生预警风暴。预警状态：待处理 / 处理中 / 已关闭。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import now
from ..models import AlertRecord, AlertRule, FeatureRecord, PriceRecord, Region, Variety
from ..security import ApiError

LEVELS: tuple[str, ...] = ("高", "中", "低")
STATUS_PENDING = "待处理"
STATUS_PROCESSING = "处理中"
STATUS_CLOSED = "已关闭"
RULE_TYPES: dict[str, str] = {
    "price_threshold": "价格阈值",
    "volatility": "波动率异常",
    "yoy": "同比异常",
    "spread": "区域价差",
}
OPERATORS: dict[str, str] = {
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
    "abs_gt": "绝对值大于",
}
OPERATOR_KEYS = tuple(OPERATORS.keys())
MAX_ALERTS_PER_RULE_WINDOW = 2


# ============================ 工具 ============================

def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    varieties = {int(v.id): v.name for v in db.execute(select(Variety)).scalars().all()}
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    return varieties, regions


def _operator_hit(operator: str, value: float, threshold: float) -> bool:
    if operator == "gt":
        return value > threshold
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    if operator == "abs_gt":
        return abs(value) > abs(threshold)
    return False


def _national_region_id(db: Session) -> int | None:
    """全国汇总地区（用于区域价差预警归属）。"""
    candidates = db.execute(select(Region)).scalars().all()
    for region in candidates:
        level = (region.level or "").strip()
        code = (region.code or "").strip().upper()
        if level in ("全国", "国家", "national") or code in ("CN", "000000", "NATIONAL", "全国"):
            return int(region.id)
    return None


def _json_channel(channel: str) -> str:
    parts = [item.strip() for item in (channel or "").replace("，", ",").split(",") if item.strip()]
    if not parts:
        parts = ["站内消息"]
    return json.dumps(parts, ensure_ascii=False)


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


# ============================ 数据读取 ============================

def _load_window_prices(db: Session, start: date, end: date) -> dict[tuple[int, int], dict[date, float]]:
    """读取窗口内日频批发价（同日多市场取均值），无批发价时回退全部市场类型。"""
    def _query(market: str | None) -> list[tuple]:
        stmt = (
            select(
                PriceRecord.variety_id,
                PriceRecord.region_id,
                PriceRecord.price_date,
                PriceRecord.price,
            )
            .where(PriceRecord.price_date >= start)
            .where(PriceRecord.price_date <= end)
        )
        if market:
            stmt = stmt.where(PriceRecord.market_type == market)
        return db.execute(stmt).all()

    rows = _query("批发")
    if not rows:
        rows = _query(None)
    grouped: dict[tuple[int, int], dict[date, list[float]]] = {}
    for variety_id, region_id, price_date, price in rows:
        if price is None:
            continue
        grouped.setdefault((int(variety_id), int(region_id)), {}).setdefault(price_date, []).append(float(price))
    result: dict[tuple[int, int], dict[date, float]] = {}
    for key, day_map in grouped.items():
        result[key] = {day: sum(values) / len(values) for day, values in day_map.items()}
    return result


def _load_window_features(db: Session, start: date, end: date) -> dict[tuple[int, int, date], dict[str, float]]:
    rows = db.execute(
        select(
            FeatureRecord.variety_id,
            FeatureRecord.region_id,
            FeatureRecord.calc_date,
            FeatureRecord.volatility_30d,
            FeatureRecord.yoy_pct,
        )
        .where(FeatureRecord.calc_date >= start)
        .where(FeatureRecord.calc_date <= end)
    ).all()
    result: dict[tuple[int, int, date], dict[str, float]] = {}
    for variety_id, region_id, calc_date, vol, yoy in rows:
        result[(int(variety_id), int(region_id), calc_date)] = {
            "volatility": float(vol or 0),
            "yoy": float(yoy or 0),
        }
    return result


# ============================ 规则匹配 ============================

def _detail_for(
    rule: AlertRule,
    variety_name: str,
    region_name: str,
    alert_date: date,
    current: float,
    threshold: float,
    extra: str = "",
) -> str:
    rule_name = RULE_TYPES.get(rule.rule_type, rule.rule_type)
    op_name = OPERATORS.get(rule.operator, rule.operator)
    text = (
        f"{alert_date.strftime('%Y-%m-%d')} {variety_name}·{region_name} {rule_name}指标为"
        f"{_round(current, 2)}，{op_name}阈值 {_round(threshold, 2)}，触发「{rule.name}」。"
    )
    if extra:
        text += extra
    return text


def _insert_alert(
    db: Session,
    rule: AlertRule,
    variety_id: int,
    region_id: int,
    alert_date: date,
    title: str,
    detail: str,
    existing_keys: set[tuple[int, int, int, date]],
    recent_counts: dict[tuple[int, int, int], int],
) -> bool:
    """写一条预警（带去重与同规则 7 天抑制）。返回是否新增。"""
    key = (int(rule.id), int(variety_id), int(region_id), alert_date)
    if key in existing_keys:
        return False
    recent_key = (int(rule.id), int(variety_id), int(region_id))
    if recent_counts.get(recent_key, 0) >= MAX_ALERTS_PER_RULE_WINDOW:
        return False
    record = AlertRecord(
        rule_id=rule.id,
        variety_id=int(variety_id),
        region_id=int(region_id),
        alert_date=alert_date,
        level=rule.level or "中",
        title=title[:250],
        detail=detail,
        status=STATUS_PENDING,
        notify_channel=_json_channel(rule.channel or "站内消息"),
        created_at=now(),
    )
    db.add(record)
    existing_keys.add(key)
    recent_counts[recent_key] = recent_counts.get(recent_key, 0) + 1
    rule.hit_count = int(rule.hit_count or 0) + 1
    db.add(rule)
    return True


def _rule_pairs(
    db: Session, rule: AlertRule, prices: dict[tuple[int, int], dict[date, float]]
) -> list[int]:
    """规则覆盖的地区列表（region_id 为空表示该品种全部有数据地区）。"""
    if rule.region_id:
        return [int(rule.region_id)]
    return sorted({int(r) for (v, r) in prices.keys() if int(v) == int(rule.variety_id)})


def evaluate_rules(
    db: Session,
    days: int = 30,
    commit: bool = True,
    rule_ids: list[int] | None = None,
) -> dict:
    """扫描最近 days 天，生成预警。返回 {created, scanned, rules}。"""
    try:
        days = int(days if days is not None else 30)
    except (TypeError, ValueError):
        raise ApiError("E4001", "扫描天数必须为整数", 400)
    days = max(1, min(90, days))
    end = date.today()
    start = end - timedelta(days=days - 1)

    stmt = select(AlertRule).where(AlertRule.enabled.is_(True))
    if rule_ids:
        stmt = stmt.where(AlertRule.id.in_([int(i) for i in rule_ids]))
    rules = db.execute(stmt.order_by(AlertRule.id)).scalars().all()
    if not rules:
        return {"created": 0, "scanned": 0, "rules": 0}

    prices = _load_window_prices(db, start, end)
    features = _load_window_features(db, start, end)
    varieties, regions = _name_maps(db)
    national_id = _national_region_id(db)

    existing_keys = {
        (int(rule_id), int(variety_id), int(region_id), alert_date)
        for rule_id, variety_id, region_id, alert_date in db.execute(
            select(AlertRecord.rule_id, AlertRecord.variety_id, AlertRecord.region_id, AlertRecord.alert_date)
            .where(AlertRecord.alert_date >= start)
            .where(AlertRecord.alert_date <= end)
        ).all()
    }
    # 同规则组合近 7 天已有预警数量（抑制用）
    recent_counts: dict[tuple[int, int, int], int] = {}
    for rule_id, variety_id, region_id, alert_date in db.execute(
        select(AlertRecord.rule_id, AlertRecord.variety_id, AlertRecord.region_id, AlertRecord.alert_date)
        .where(AlertRecord.alert_date >= end - timedelta(days=7))
        .where(AlertRecord.alert_date <= end)
    ).all():
        key = (int(rule_id), int(variety_id), int(region_id))
        recent_counts[key] = recent_counts.get(key, 0) + 1

    created = 0
    scanned = 0
    for rule in rules:
        variety_id = int(rule.variety_id)
        variety_name = varieties.get(variety_id, "")
        threshold = float(rule.threshold or 0)
        if rule.rule_type == "spread":
            # 区域价差：逐日计算该品种跨地区最高价与最低价之差
            day_prices: dict[date, dict[int, float]] = {}
            for (vid, rid), day_map in prices.items():
                if int(vid) != variety_id:
                    continue
                for day, price in day_map.items():
                    day_prices.setdefault(day, {})[int(rid)] = price
            spread_region = int(rule.region_id) if rule.region_id else national_id
            if not spread_region:
                spread_region = min(regions.keys()) if regions else 1
            for day in sorted(day_prices.keys()):
                region_day = day_prices[day]
                if len(region_day) < 2:
                    continue
                scanned += 1
                high_region_id = max(region_day, key=lambda rid: region_day[rid])
                low_region_id = min(region_day, key=lambda rid: region_day[rid])
                spread = region_day[high_region_id] - region_day[low_region_id]
                if not _operator_hit(rule.operator, spread, threshold):
                    continue
                region_name = regions.get(spread_region, "全国")
                extra = (
                    f"最高价地区为{regions.get(high_region_id, '')}（{_round(region_day[high_region_id], 2)}），"
                    f"最低价地区为{regions.get(low_region_id, '')}（{_round(region_day[low_region_id], 2)}）。"
                )
                detail = _detail_for(rule, variety_name, region_name, day, spread, threshold, extra)
                title = f"{variety_name}区域价差预警"
                if _insert_alert(db, rule, variety_id, spread_region, day, title, detail, existing_keys, recent_counts):
                    created += 1
            continue

        region_ids = _rule_pairs(db, rule, prices)
        for region_id in region_ids:
            region_name = regions.get(region_id, "")
            day_map = prices.get((variety_id, region_id), {})
            for day in sorted(day_map.keys()):
                price = day_map[day]
                current: float | None = None
                extra = ""
                if rule.rule_type == "price_threshold":
                    current = float(price)
                elif rule.rule_type in ("volatility", "yoy"):
                    feature = features.get((variety_id, region_id, day))
                    if feature is None:
                        continue
                    current = feature["volatility"] if rule.rule_type == "volatility" else feature["yoy"]
                    extra = f"当日批发价 {_round(price, 2)} 元/公斤。"
                else:
                    continue
                if current is None:
                    continue
                scanned += 1
                if not _operator_hit(rule.operator, current, threshold):
                    continue
                type_name = RULE_TYPES.get(rule.rule_type, rule.rule_type)
                detail = _detail_for(rule, variety_name, region_name, day, current, threshold, extra)
                title = f"{variety_name}{region_name}{type_name}预警"
                if _insert_alert(db, rule, variety_id, region_id, day, title, detail, existing_keys, recent_counts):
                    created += 1

    if commit:
        db.commit()
    else:
        db.flush()
    return {"created": created, "scanned": scanned, "rules": len(rules)}


# ============================ 预警查询与处置 ============================

def serialize_alert(record: AlertRecord, variety_name: str, region_name: str, rule_name: str) -> dict:
    return {
        "id": record.id,
        "level": record.level,
        "title": record.title,
        "variety_id": record.variety_id,
        "variety": variety_name,
        "region_id": record.region_id,
        "region": region_name,
        "alert_date": record.alert_date.strftime("%Y-%m-%d") if record.alert_date else "",
        "status": record.status,
        "rule_name": rule_name,
        "detail": record.detail,
        "handler": record.handler or "",
        "handled_at": record.handled_at.strftime("%Y-%m-%dT%H:%M:%S") if record.handled_at else "",
        "handle_note": record.handle_note or "",
        "notify_channel": record.notify_channel or "",
        "created_at": record.created_at.strftime("%Y-%m-%dT%H:%M:%S") if record.created_at else "",
    }


def list_alerts(
    db: Session,
    status: str | None = None,
    level: str | None = None,
    variety_id: int | None = None,
    region_id: int | None = None,
    page: int = 1,
    page_size: int = 15,
) -> tuple[list[dict], int]:
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 15)))
    conditions = []
    if status:
        conditions.append(AlertRecord.status == str(status))
    if level:
        conditions.append(AlertRecord.level == str(level))
    if variety_id:
        conditions.append(AlertRecord.variety_id == int(variety_id))
    if region_id:
        conditions.append(AlertRecord.region_id == int(region_id))

    count_stmt = select(func.count(AlertRecord.id))
    list_stmt = select(AlertRecord).order_by(AlertRecord.alert_date.desc(), AlertRecord.id.desc())
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar() or 0)
    rows = db.execute(list_stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()

    varieties, regions = _name_maps(db)
    rule_map = {
        int(rule.id): rule.name
        for rule in db.execute(
            select(AlertRule).where(AlertRule.id.in_([r.rule_id for r in rows] or [0]))
        ).scalars().all()
    }
    items = [
        serialize_alert(
            row,
            varieties.get(int(row.variety_id), ""),
            regions.get(int(row.region_id), ""),
            rule_map.get(int(row.rule_id), ""),
        )
        for row in rows
    ]
    return items, total


def get_alert(db: Session, alert_id: int) -> AlertRecord:
    record = db.get(AlertRecord, int(alert_id))
    if record is None:
        raise ApiError("E4040", "预警记录不存在", 404)
    return record


def alert_detail(db: Session, alert_id: int) -> dict:
    record = get_alert(db, alert_id)
    varieties, regions = _name_maps(db)
    rule = db.get(AlertRule, record.rule_id)
    return serialize_alert(
        record,
        varieties.get(int(record.variety_id), ""),
        regions.get(int(record.region_id), ""),
        rule.name if rule else "",
    )


def _handler_name(user: Any) -> str:
    if user is None:
        return "system"
    display = getattr(user, "display_name", None) or getattr(user, "username", None) or "system"
    return str(display)


def ack_alert(db: Session, alert_id: int, user: Any, note: str = "", commit: bool = True) -> dict:
    record = get_alert(db, alert_id)
    if record.status == STATUS_CLOSED:
        raise ApiError("E4090", "该预警已关闭，无法再次确认", 409)
    record.status = STATUS_PROCESSING
    record.handler = _handler_name(user)
    record.handled_at = now()
    if note:
        record.handle_note = str(note)[:1000]
    db.add(record)
    if commit:
        db.commit()
    return {"ok": True, "status": record.status}


def close_alert(
    db: Session,
    alert_id: int,
    user: Any,
    note: str = "",
    result: str = "",
    commit: bool = True,
) -> dict:
    record = get_alert(db, alert_id)
    record.status = STATUS_CLOSED
    record.handler = _handler_name(user)
    record.handled_at = now()
    note_text = str(note or "")
    if result:
        note_text = (note_text + "；" if note_text else "") + f"处置结果：{result}"
    if note_text:
        record.handle_note = note_text[:1000]
    db.add(record)
    if commit:
        db.commit()
    return {"ok": True, "status": record.status}


# ============================ 统计 ============================

def stats(db: Session) -> dict:
    """预警统计：未处置数、近 30 天总量、按级别/状态分布、近 14 天趋势、处置率与误报率。"""
    today = date.today()
    start_30 = today - timedelta(days=29)

    open_count = int(
        db.execute(
            select(func.count(AlertRecord.id)).where(AlertRecord.status.in_([STATUS_PENDING, STATUS_PROCESSING]))
        ).scalar()
        or 0
    )
    total_30d = int(
        db.execute(
            select(func.count(AlertRecord.id))
            .where(AlertRecord.alert_date >= start_30)
            .where(AlertRecord.alert_date <= today)
        ).scalar()
        or 0
    )
    by_level = [
        {"level": level, "count": int(count)}
        for level, count in db.execute(
            select(AlertRecord.level, func.count(AlertRecord.id)).group_by(AlertRecord.level)
        ).all()
    ]
    by_status = [
        {"status": status, "count": int(count)}
        for status, count in db.execute(
            select(AlertRecord.status, func.count(AlertRecord.id)).group_by(AlertRecord.status)
        ).all()
    ]
    trend_counts = dict(
        db.execute(
            select(AlertRecord.alert_date, func.count(AlertRecord.id))
            .where(AlertRecord.alert_date >= today - timedelta(days=13))
            .where(AlertRecord.alert_date <= today)
            .group_by(AlertRecord.alert_date)
        ).all()
    )
    trend = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        trend.append({"date": day.strftime("%Y-%m-%d"), "count": int(trend_counts.get(day, 0))})

    handled = int(
        db.execute(
            select(func.count(AlertRecord.id))
            .where(AlertRecord.alert_date >= start_30)
            .where(AlertRecord.status.isnot(None))
            .where(AlertRecord.status != STATUS_PENDING)
        ).scalar()
        or 0
    )
    false_positive = int(
        db.execute(
            select(func.count(AlertRecord.id))
            .where(AlertRecord.alert_date >= start_30)
            .where(AlertRecord.handle_note.like("%误报%"))
        ).scalar()
        or 0
    )
    recall_rate = round(handled / total_30d * 100.0, 2) if total_30d else 0.0
    false_positive_rate = round(false_positive / total_30d * 100.0, 2) if total_30d else 0.0
    return {
        "open_count": open_count,
        "total_30d": total_30d,
        "by_level": by_level,
        "by_status": by_status,
        "trend": trend,
        "recall_rate": recall_rate,
        "false_positive_rate": false_positive_rate,
    }


# ============================ 规则管理 ============================

def serialize_rule(rule: AlertRule, variety_name: str, region_name: str) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "variety_id": rule.variety_id,
        "variety": variety_name,
        "region_id": rule.region_id,
        "region": region_name or "全部地区",
        "rule_type": rule.rule_type,
        "rule_type_name": RULE_TYPES.get(rule.rule_type, rule.rule_type),
        "operator": rule.operator,
        "threshold": round(float(rule.threshold or 0), 4),
        "window_days": int(rule.window_days or 7),
        "level": rule.level,
        "enabled": bool(rule.enabled),
        "channel": rule.channel,
        "hit_count": int(rule.hit_count or 0),
        "created_at": rule.created_at.strftime("%Y-%m-%dT%H:%M:%S") if rule.created_at else "",
    }


def list_rules(db: Session) -> list[dict]:
    varieties, regions = _name_maps(db)
    rules = db.execute(select(AlertRule).order_by(AlertRule.id)).scalars().all()
    return [
        serialize_rule(
            rule,
            varieties.get(int(rule.variety_id), ""),
            regions.get(int(rule.region_id), "") if rule.region_id else "",
        )
        for rule in rules
    ]


def _validate_rule_payload(db: Session, payload: dict, rule: AlertRule | None = None) -> dict:
    """校验并规整规则字段；部分更新时与旧值合并。"""
    merged: dict[str, Any] = {}
    if rule is not None:
        merged = {
            "name": rule.name,
            "variety_id": rule.variety_id,
            "region_id": rule.region_id,
            "rule_type": rule.rule_type,
            "operator": rule.operator,
            "threshold": rule.threshold,
            "window_days": rule.window_days,
            "level": rule.level,
            "enabled": rule.enabled,
            "channel": rule.channel,
        }
    for key in ("name", "variety_id", "region_id", "rule_type", "operator", "threshold", "window_days", "level", "enabled", "channel"):
        if key in payload:
            merged[key] = payload[key]

    name = str(merged.get("name") or "").strip()
    if not name:
        raise ApiError("E4001", "请填写规则名称", 400)
    try:
        variety_id = int(merged.get("variety_id"))
    except (TypeError, ValueError):
        raise ApiError("E4001", "请选择预警品种", 400)
    if db.get(Variety, variety_id) is None:
        raise ApiError("E4040", "品种不存在", 404)
    region_id = merged.get("region_id")
    if region_id in ("", 0, "0", None):
        region_id = None
    else:
        try:
            region_id = int(region_id)
        except (TypeError, ValueError):
            raise ApiError("E4001", "地区参数格式不正确", 400)
        if db.get(Region, region_id) is None:
            raise ApiError("E4040", "地区不存在", 404)
    rule_type = str(merged.get("rule_type") or "price_threshold")
    if rule_type not in RULE_TYPES:
        raise ApiError("E4001", f"不支持的规则类型：{rule_type}", 400)
    operator = str(merged.get("operator") or "gt")
    if operator not in OPERATORS:
        raise ApiError("E4001", f"不支持的比较方式：{operator}", 400)
    try:
        threshold = float(merged.get("threshold", 0))
    except (TypeError, ValueError):
        raise ApiError("E4001", "阈值必须为数字", 400)
    try:
        window_days = int(merged.get("window_days", 7) or 7)
    except (TypeError, ValueError):
        raise ApiError("E4001", "统计窗口必须为整数", 400)
    window_days = max(1, min(90, window_days))
    level = str(merged.get("level") or "中")
    if level not in LEVELS:
        raise ApiError("E4001", "预警级别仅支持 高/中/低", 400)
    enabled = merged.get("enabled", True)
    enabled = bool(enabled) if not isinstance(enabled, str) else enabled.lower() in ("true", "1", "是", "启用")
    channel = str(merged.get("channel") or "站内消息")
    return {
        "name": name[:128],
        "variety_id": variety_id,
        "region_id": region_id,
        "rule_type": rule_type,
        "operator": operator,
        "threshold": round(threshold, 4),
        "window_days": window_days,
        "level": level,
        "enabled": enabled,
        "channel": channel[:64],
    }


def create_rule(db: Session, payload: dict, user: Any, commit: bool = True) -> AlertRule:
    data = _validate_rule_payload(db, payload)
    rule = AlertRule(
        **data,
        hit_count=0,
        created_by=_handler_name(user),
        created_at=now(),
    )
    db.add(rule)
    if commit:
        db.commit()
    else:
        db.flush()
    return rule


def update_rule(db: Session, rule_id: int, payload: dict, commit: bool = True) -> AlertRule:
    rule = db.get(AlertRule, int(rule_id))
    if rule is None:
        raise ApiError("E4040", "预警规则不存在", 404)
    data = _validate_rule_payload(db, payload, rule)
    for key, value in data.items():
        setattr(rule, key, value)
    db.add(rule)
    if commit:
        db.commit()
    else:
        db.flush()
    return rule


def delete_rule(db: Session, rule_id: int, commit: bool = True) -> None:
    rule = db.get(AlertRule, int(rule_id))
    if rule is None:
        raise ApiError("E4040", "预警规则不存在", 404)
    has_alerts = db.execute(
        select(func.count(AlertRecord.id)).where(AlertRecord.rule_id == rule.id)
    ).scalar()
    if has_alerts:
        raise ApiError("E4090", "该规则已产生预警记录，请先停用而不是删除", 409)
    db.delete(rule)
    if commit:
        db.commit()


def toggle_rule(db: Session, rule_id: int, commit: bool = True) -> dict:
    rule = db.get(AlertRule, int(rule_id))
    if rule is None:
        raise ApiError("E4040", "预警规则不存在", 404)
    rule.enabled = not bool(rule.enabled)
    db.add(rule)
    if commit:
        db.commit()
    return {"ok": True, "enabled": bool(rule.enabled)}


def rule_export_rows(db: Session, rules: list[dict] | None = None) -> list[list[Any]]:
    rules = rules if rules is not None else list_rules(db)
    rows: list[list[Any]] = [
        ["规则名称", "品种", "地区", "规则类型", "比较方式", "阈值", "统计窗口(天)", "级别", "状态", "命中次数", "创建时间"]
    ]
    for rule in rules:
        rows.append(
            [
                rule["name"],
                rule["variety"],
                rule["region"],
                rule["rule_type_name"],
                OPERATORS.get(rule["operator"], rule["operator"]),
                rule["threshold"],
                rule["window_days"],
                rule["level"],
                "启用" if rule["enabled"] else "停用",
                rule["hit_count"],
                rule["created_at"],
            ]
        )
    return rows
