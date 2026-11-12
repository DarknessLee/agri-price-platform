"""模型治理服务：漂移监控（日收益率分布 PSI + 近期回测误差）。

漂移判定口径（契约 M2 §1）：
- 当前分布：最近 ``DRIFT_WINDOW_DAYS`` 天（默认 90 天）的日收益率；
- 基线分布：当前窗口之前 ``DRIFT_BASELINE_DAYS`` 天（默认 180 天）的日收益率；
- 使用收益率先做居中对齐（价格水平差异不影响分布形状），样本不足时退化为 30 日波动率；
- PSI（Population Stability Index）按 ``DRIFT_BINS`` 个分箱计算：
  PSI < 0.1 平稳，0.1 ~ 0.25 关注，> 0.25 漂移；
- 近期 MAPE 用最近 30 天回测记录，缺少回测记录时回退到训练时留出评估 MAPE。

窗口取 90/180 天而非 30/90 天，是因为价格日收益率在高频上噪声大，
30 天窗口下每箱样本过少会把随机波动误判为漂移。
接口结果缓存 ``CACHE_TTL_PERFORMANCE`` 秒，避免每次请求重复查询 30 个模型。
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache
from ..config import (
    CACHE_TTL_PERFORMANCE,
    DRIFT_BASELINE_DAYS,
    DRIFT_BINS,
    DRIFT_PSI_DRIFT,
    DRIFT_PSI_WATCH,
    DRIFT_WINDOW_DAYS,
)
from ..database import now
from ..models import BacktestRecord, FeatureRecord, ModelVersion, PriceRecord, Region, Variety
from ..security import ApiError

logger = logging.getLogger(__name__)

DRIFT_STABLE = "平稳"
DRIFT_WATCH = "关注"
DRIFT_DRIFT = "漂移"


def drift_level(psi_value: float) -> str:
    """按 PSI 阈值给出中文漂移等级。"""
    try:
        value = float(psi_value)
    except (TypeError, ValueError):
        value = 0.0
    if value > DRIFT_PSI_DRIFT:
        return DRIFT_DRIFT
    if value >= DRIFT_PSI_WATCH:
        return DRIFT_WATCH
    return DRIFT_STABLE


def _clean(values: Any) -> np.ndarray:
    """转成一维浮点数组，过滤空值与异常值。"""
    array = np.asarray([value for value in (values or [])], dtype=object)
    result: list[float] = []
    for value in array:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(number):
            result.append(number)
    return np.asarray(result, dtype=float)


def population_stability_index(baseline: Any, current: Any, bins: int = DRIFT_BINS) -> float:
    """计算 PSI：以基线分位数为分箱边界，比较两期分布差异。"""
    base = _clean(baseline)
    cur = _clean(current)
    if base.size < 5 or cur.size < 5:
        return 0.0
    bins = max(2, int(bins or 10))
    edges = np.unique(np.quantile(base, np.linspace(0.0, 1.0, bins + 1)))
    if edges.size < 3:
        low = float(min(base.min(), cur.min()))
        high = float(max(base.max(), cur.max()))
        if high <= low:
            return 0.0
        edges = np.linspace(low, high, bins + 1)
    base_pct = np.histogram(np.clip(base, edges[0], edges[-1]), bins=edges)[0].astype(float) / base.size
    cur_pct = np.histogram(np.clip(cur, edges[0], edges[-1]), bins=edges)[0].astype(float) / cur.size
    base_pct = np.clip(base_pct, 1e-4, None)
    cur_pct = np.clip(cur_pct, 1e-4, None)
    value = float(np.sum((cur_pct - base_pct) * np.log(cur_pct / base_pct)))
    return round(max(0.0, value), 4)


def _latest_price_date(db: Session, variety_id: int, region_id: int) -> date | None:
    return db.execute(
        select(func.max(PriceRecord.price_date))
        .where(PriceRecord.variety_id == int(variety_id))
        .where(PriceRecord.region_id == int(region_id))
    ).scalar()


def _windows(end: date, window_days: int) -> tuple[date, date, date, date]:
    """拆出基线窗口与当前窗口：当前取最近 ``window_days`` 天，基线取其前的 ``DRIFT_BASELINE_DAYS`` 天。"""
    recent_days = max(30, int(window_days or DRIFT_WINDOW_DAYS))
    recent_start = end - timedelta(days=recent_days - 1)
    baseline_end = recent_start - timedelta(days=1)
    baseline_days = max(recent_days, int(DRIFT_BASELINE_DAYS or 0))
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)
    return baseline_start, baseline_end, recent_start, end


def _feature_values(
    db: Session, variety_id: int, region_id: int, start: date, end: date
) -> list[float]:
    rows = db.execute(
        select(FeatureRecord.volatility_30d)
        .where(FeatureRecord.variety_id == int(variety_id))
        .where(FeatureRecord.region_id == int(region_id))
        .where(FeatureRecord.calc_date >= start)
        .where(FeatureRecord.calc_date <= end)
    ).scalars().all()
    return [float(value) for value in rows if value is not None]


def _daily_returns(
    db: Session, variety_id: int, region_id: int, start: date, end: date
) -> list[float]:
    """按日聚合批发均价后计算日收益率（百分比），用于缺少特征记录时的退化口径。"""
    base_conditions = [
        PriceRecord.variety_id == int(variety_id),
        PriceRecord.region_id == int(region_id),
        PriceRecord.price_date >= start - timedelta(days=7),
        PriceRecord.price_date <= end,
    ]
    for market_type in ("批发", None):
        conditions = list(base_conditions)
        if market_type is not None:
            conditions.append(PriceRecord.market_type == market_type)
        rows = db.execute(
            select(PriceRecord.price_date, func.avg(PriceRecord.price))
            .where(*conditions)
            .group_by(PriceRecord.price_date)
            .order_by(PriceRecord.price_date)
        ).all()
        if len(rows) >= 5:
            break
    else:  # pragma: no cover - 双重退化均无数据时返回空
        return []

    dates: list[date] = []
    prices: list[float] = []
    for price_date, price in rows:
        if price is None or float(price) <= 0:
            continue
        dates.append(price_date)
        prices.append(float(price))
    returns: list[float] = []
    for index in range(1, len(prices)):
        if dates[index] < start:
            continue
        previous = prices[index - 1]
        if previous <= 0:
            continue
        returns.append((prices[index] - previous) / previous * 100.0)
    return returns


def _psi_of_pair(
    db: Session, variety_id: int, region_id: int, window_days: int
) -> float:
    end = _latest_price_date(db, variety_id, region_id)
    if end is None:
        return 0.0
    baseline_start, baseline_end, recent_start, recent_end = _windows(end, window_days)
    # 主口径：日收益率分布（价格水平平移不影响分布形状，适合监控价格行为漂移）
    baseline = _daily_returns(db, variety_id, region_id, baseline_start, baseline_end)
    current = _daily_returns(db, variety_id, region_id, recent_start, recent_end)
    if len(baseline) < 20 or len(current) < 20:
        # 退化口径：特征表中的 30 日波动率（缺少价格流水时仍可评估）
        baseline = _feature_values(db, variety_id, region_id, baseline_start, baseline_end)
        current = _feature_values(db, variety_id, region_id, recent_start, recent_end)
    return population_stability_index(baseline, current)


def _recent_mape(db: Session, model: ModelVersion, end: date) -> float:
    """最近 30 天回测 MAPE；缺少回测记录时回退到训练留出评估的 MAPE。"""
    rows = db.execute(
        select(BacktestRecord.actual, BacktestRecord.predicted)
        .where(BacktestRecord.model_id == int(model.id))
        .where(BacktestRecord.date >= end - timedelta(days=max(7, DRIFT_WINDOW_DAYS) - 1))
        .where(BacktestRecord.date <= end)
    ).all()
    errors: list[float] = []
    for actual, predicted in rows:
        try:
            actual_value = float(actual)
            predicted_value = float(predicted)
        except (TypeError, ValueError):
            continue
        if actual_value > 0:
            errors.append(abs(predicted_value - actual_value) / actual_value * 100.0)
    if len(errors) >= 7:
        return round(float(np.mean(errors)), 2)

    try:
        params = json.loads(model.params or "{}")
        holdout = params.get("holdout_metrics") or {}
        if holdout.get("mape") is not None:
            return round(float(holdout["mape"]), 2)
    except (ValueError, TypeError):
        pass
    return round(float(model.mape or 0), 2)


def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    varieties = {
        int(v.id): v.name
        for v in db.execute(select(Variety)).scalars().all()
    }
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    return varieties, regions


def _compute_drift(db: Session, window: int) -> dict:
    varieties, regions = _name_maps(db)
    models = db.execute(
        select(ModelVersion).where(ModelVersion.is_active.is_(True)).order_by(ModelVersion.id)
    ).scalars().all()
    checked_at = now().strftime("%Y-%m-%dT%H:%M:%S")
    items: list[dict] = []
    psi_values: list[float] = []
    counts = {DRIFT_STABLE: 0, DRIFT_WATCH: 0, DRIFT_DRIFT: 0}
    for model in models:
        variety_id = int(model.variety_id or 0)
        region_id = int(model.region_id or 0)
        end = _latest_price_date(db, variety_id, region_id)
        try:
            psi_value = _psi_of_pair(db, variety_id, region_id, window)
        except Exception:  # pragma: no cover - 单个模型查询失败不阻断整体监控
            logger.exception("计算模型漂移指标失败：model_id=%s", model.id)
            psi_value = 0.0
        level = drift_level(psi_value)
        recent_mape = (
            _recent_mape(db, model, end) if end is not None else round(float(model.mape or 0), 2)
        )
        mape = round(float(model.mape or 0), 2)
        counts[level] += 1
        psi_values.append(float(psi_value))
        items.append(
            {
                "model_id": model.id,
                "key": model.key,
                "name": model.name,
                "algorithm": model.algorithm,
                "variety": varieties.get(variety_id, ""),
                "region": regions.get(region_id, ""),
                "status": model.status,
                "mape": mape,
                "recent_mape": round(recent_mape, 2),
                "psi": round(float(psi_value), 4),
                "drift_level": level,
                "mape_change": round(recent_mape - mape, 2),
                "trained_at": model.trained_at.strftime("%Y-%m-%dT%H:%M:%S") if model.trained_at else "",
                "last_checked_at": checked_at,
            }
        )

    severity = {DRIFT_DRIFT: 0, DRIFT_WATCH: 1, DRIFT_STABLE: 2}
    items.sort(key=lambda item: (severity.get(item["drift_level"], 3), -item["psi"]))
    summary = {
        "total": len(items),
        "stable": counts[DRIFT_STABLE],
        "watch": counts[DRIFT_WATCH],
        "drifted": counts[DRIFT_DRIFT],
        "avg_psi": round(float(np.mean(psi_values)), 4) if psi_values else 0.0,
    }
    return {"items": items, "summary": summary, "window": int(window), "checked_at": checked_at}


def model_drift(db: Session, window: int = 90) -> dict:
    """模型漂移监控：返回各在用模型的 PSI、近期 MAPE 与漂移等级（结果缓存 120 秒）。"""
    try:
        window_days = int(window if window is not None else 90)
    except (TypeError, ValueError):
        raise ApiError("E4001", "监控窗口必须为整数", 400)
    if window_days < 30 or window_days > 365:
        raise ApiError("E4001", "监控窗口需在 30~365 天之间", 400)

    cache_key = cache.make_key("models", "drift", window_days)
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached
    payload = _compute_drift(db, window_days)
    cache.set(cache_key, payload, CACHE_TTL_PERFORMANCE)
    return payload
