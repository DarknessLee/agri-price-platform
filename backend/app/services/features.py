"""特征工程：从价格事实表构造日频价格序列、训练特征矩阵与特征快照。

对外主要函数：
- load_price_series(db, variety_id, region_id, ...)   读取单条日频批发价序列（跨市场取均值）
- prepare_series(series)                              补齐日期缺口、插值成连续日序列
- build_training_matrix(db, variety_id, region_id)    构造 GBR 训练矩阵 X / y / 特征名
- build_feature_row(history, target_date, ...)        递归预测时逐日构造特征行
- ensure_feature_records(db, days=30)                 补算 FeatureRecord（同比/环比/波动率/季节/指数）
- holiday_flag(d) / feature_label(name)               节假日标记与中文因子名

设计说明：成本/运费/气象三类业务指数优先取 FeatureRecord 已有值，缺失时按日期生成
稳定的业务级指标；预测未来日采用最后已知值（外推），保证训练与服务特征口径一致。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FeatureRecord, PriceRecord, Region, Variety

# 建模只用批发价序列；零售价仅用于价格传导展示
DEFAULT_MARKET_TYPE = "批发"

# GBR 使用的基础特征列（顺序固定，训练与递归预测共用）
GBR_FEATURES: list[str] = [
    "lag1",
    "lag7",
    "lag14",
    "lag30",
    "lag365",
    "roll_mean_7",
    "roll_mean_30",
    "roll_std_7",
    "roll_std_30",
    "sin_doy",
    "cos_doy",
    "sin_doy2",
    "cos_doy2",
    "weekday",
    "holiday",
    "yoy",
    "mom",
    "cost_index",
    "freight_index",
    "weather_score",
    "volatility",
    "seasonal_index",
]

FEATURE_LABELS: dict[str, str] = {
    "lag1": "前一日价格",
    "lag7": "前七日价格",
    "lag14": "前十四日价格",
    "lag30": "前三十日价格",
    "lag365": "去年同期价格",
    "roll_mean_7": "七日均价",
    "roll_mean_30": "三十日均价",
    "roll_std_7": "七日波动",
    "roll_std_30": "三十日波动",
    "sin_doy": "年周期（正弦）",
    "cos_doy": "年周期（余弦）",
    "sin_doy2": "半年周期（正弦）",
    "cos_doy2": "半年周期（余弦）",
    "weekday": "星期效应",
    "holiday": "节假日效应",
    "yoy": "同比涨幅",
    "mom": "环比涨幅",
    "cost_index": "成本指数",
    "freight_index": "运费指数",
    "weather_score": "气象指数",
    "volatility": "近期波动率",
    "seasonal_index": "季节指数",
}

# 春节窗口（近似，用于节假日特征）
_SPRING_FESTIVAL: dict[int, tuple[int, int, int, int]] = {
    2023: (1, 21, 1, 27),
    2024: (2, 10, 2, 17),
    2025: (1, 28, 2, 4),
    2026: (2, 16, 2, 22),
    2027: (2, 6, 2, 12),
}
_FIXED_HOLIDAYS: set[tuple[int, int]] = {
    (1, 1),
    (1, 2),
    (1, 3),
    (4, 4),
    (4, 5),
    (5, 1),
    (5, 2),
    (5, 3),
    (6, 22),
    (10, 1),
    (10, 2),
    (10, 3),
    (10, 4),
    (10, 5),
    (10, 6),
    (10, 7),
}


def feature_label(name: str) -> str:
    """特征英文名转中文展示名。"""
    return FEATURE_LABELS.get(name, name)


def holiday_flag(d: date | datetime | pd.Timestamp) -> int:
    """节假日/周末标记：周末或法定节假日返回 1。"""
    if isinstance(d, pd.Timestamp):
        d = d.date()
    elif isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:
        return 1
    if (d.month, d.day) in _FIXED_HOLIDAYS:
        return 1
    window = _SPRING_FESTIVAL.get(d.year)
    if window:
        start = date(d.year, window[0], window[1])
        end = date(d.year, window[2], window[3])
        # 春节前后 5 天纳入节庆效应
        if start - timedelta(days=5) <= d <= end + timedelta(days=2):
            return 1
    return 0


def _indicator_values(d: date, variety_id: int, region_id: int) -> dict[str, float]:
    """业务级指数（成本/运费/气象）的稳定生成口径，仅用于特征缺失兜底。"""
    ordv = d.toordinal()
    cost = 100.0 + 8.0 * math.sin(2 * math.pi * ordv / 365.25 + variety_id * 0.37)
    freight = 100.0 + 10.0 * math.sin(2 * math.pi * ordv / 180.0 + region_id * 0.53) + 3.0 * math.cos(
        2 * math.pi * ordv / 45.0
    )
    weather = 100.0 + 12.0 * math.sin(2 * math.pi * ordv / 365.25 + 1.6) + 4.0 * math.sin(
        2 * math.pi * ordv / 10.0 + region_id * 0.71
    )
    return {
        "cost_index": round(cost, 2),
        "freight_index": round(freight, 2),
        "weather_score": round(weather, 2),
    }


# ---------------------------- 价格序列 ----------------------------

def load_price_series(
    db: Session,
    variety_id: int,
    region_id: int,
    market_type: str | None = DEFAULT_MARKET_TYPE,
    start: date | None = None,
    end: date | None = None,
) -> pd.Series:
    """读取品种×地区的日频价格均值序列（索引为日期，升序）。

    优先批发价；若指定市场类型无数据则回退为全部市场类型均值，保证空数据时返回空序列。
    """
    def _query(market: str | None) -> list[tuple[date, float]]:
        stmt = (
            select(PriceRecord.price_date, PriceRecord.price)
            .where(PriceRecord.variety_id == int(variety_id))
            .where(PriceRecord.region_id == int(region_id))
        )
        if market:
            stmt = stmt.where(PriceRecord.market_type == market)
        if start:
            stmt = stmt.where(PriceRecord.price_date >= start)
        if end:
            stmt = stmt.where(PriceRecord.price_date <= end)
        rows = db.execute(stmt.order_by(PriceRecord.price_date)).all()
        return [(r[0], float(r[1])) for r in rows if r[1] is not None]

    rows = _query(market_type) if market_type else _query(None)
    if not rows and market_type:
        rows = _query(None)
    if not rows:
        return pd.Series(dtype="float64", name="price")
    # 同日多市场取均值
    df = pd.DataFrame(rows, columns=["d", "price"])
    agg = df.groupby("d", as_index=False)["price"].mean()
    idx = pd.to_datetime(agg["d"])
    series = pd.Series(agg["price"].astype(float).to_numpy(), index=idx, name="price")
    return series.sort_index()


def prepare_series(series: pd.Series) -> pd.Series:
    """补齐缺失日期为连续日频序列（线性插值，两端按最近值延伸）。"""
    if series is None or len(series) == 0:
        return pd.Series(dtype="float64", name="price")
    s = series.astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s[s > 0]
    if len(s) < 2:
        return s
    full_index = pd.date_range(s.index.min(), s.index.max(), freq="D")
    s = s.reindex(full_index)
    s = s.interpolate(method="linear", limit_direction="both")
    s = s.ffill().bfill()
    return s.rename("price")


def load_indicator_frame(db: Session, variety_id: int, region_id: int) -> pd.DataFrame:
    """读取已有 FeatureRecord 中的成本/运费/气象/节假日指标（可能为空表）。"""
    rows = db.execute(
        select(
            FeatureRecord.calc_date,
            FeatureRecord.cost_index,
            FeatureRecord.freight_index,
            FeatureRecord.weather_score,
            FeatureRecord.holiday_flag,
        )
        .where(FeatureRecord.variety_id == int(variety_id))
        .where(FeatureRecord.region_id == int(region_id))
        .order_by(FeatureRecord.calc_date)
    ).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["calc_date", "cost_index", "freight_index", "weather_score", "holiday_flag"])
    df["calc_date"] = pd.to_datetime(df["calc_date"])
    return df.set_index("calc_date").sort_index()


# ---------------------------- 向量化特征 ----------------------------

def _feature_frame(
    series: pd.Series,
    indicators: pd.DataFrame | None = None,
    variety_id: int = 1,
    region_id: int = 1,
) -> pd.DataFrame:
    """由价格序列生成训练特征矩阵（索引日期，含 price 列）。"""
    s = series.astype(float).sort_index()
    df = pd.DataFrame(index=s.index)
    df["price"] = s

    df["lag1"] = s.shift(1)
    df["lag7"] = s.shift(7)
    df["lag14"] = s.shift(14)
    df["lag30"] = s.shift(30)
    # 历史不足一年时用 30 日均价兜底，保持特征列稳定
    lag365 = s.shift(365)
    df["lag365"] = lag365.fillna(df["lag30"]).fillna(df["lag1"])
    shifted = s.shift(1)
    df["roll_mean_7"] = shifted.rolling(7, min_periods=3).mean()
    df["roll_mean_30"] = shifted.rolling(30, min_periods=7).mean()
    df["roll_std_7"] = shifted.rolling(7, min_periods=3).std(ddof=0)
    df["roll_std_30"] = shifted.rolling(30, min_periods=7).std(ddof=0)

    doy = df.index.dayofyear.to_numpy(dtype=float)
    df["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
    df["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)
    df["sin_doy2"] = np.sin(4 * np.pi * doy / 365.25)
    df["cos_doy2"] = np.cos(4 * np.pi * doy / 365.25)
    df["weekday"] = df.index.weekday.astype(float)

    df["yoy"] = (s / df["lag365"].replace(0, np.nan) - 1.0) * 100.0
    df["mom"] = (s / df["lag30"].replace(0, np.nan) - 1.0) * 100.0

    returns = s.pct_change()
    df["volatility"] = returns.rolling(30, min_periods=7).std(ddof=0) * math.sqrt(365.0) * 100.0

    centered = s.rolling(365, center=True, min_periods=30).mean()
    df["seasonal_index"] = (s / centered.replace(0, np.nan) * 100.0).fillna(100.0)

    # 指数类特征：优先库内值，缺失按日期生成
    fallback = pd.DataFrame(
        [_indicator_values(d.date(), variety_id, region_id) for d in df.index], index=df.index
    )
    for col in ("cost_index", "freight_index", "weather_score"):
        if indicators is not None and not indicators.empty and col in indicators.columns:
            db_col = indicators[col].reindex(df.index)
            df[col] = db_col.fillna(fallback[col])
        else:
            df[col] = fallback[col]

    if indicators is not None and not indicators.empty and "holiday_flag" in indicators.columns:
        df["holiday"] = indicators["holiday_flag"].reindex(df.index)
    else:
        df["holiday"] = np.nan
    computed_holiday = np.array([holiday_flag(d.date()) for d in df.index], dtype=float)
    df["holiday"] = df["holiday"].fillna(pd.Series(computed_holiday, index=df.index))
    df["holiday"] = df["holiday"].astype(float)

    # 数值列统一清洗
    for col in GBR_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].replace([np.inf, -np.inf], np.nan)
    # 核心滞后特征缺失的行后续剔除；其余特征做中位数兜底
    return df


def _last_indicator_row(indicators: pd.DataFrame | None, variety_id: int, region_id: int) -> dict[str, float]:
    """未来日的指数取值：库内最后一行优先，否则按日期生成。"""
    if indicators is not None and not indicators.empty:
        last = indicators.iloc[-1]
        return {
            "cost_index": float(last.get("cost_index", 100.0)),
            "freight_index": float(last.get("freight_index", 100.0)),
            "weather_score": float(last.get("weather_score", 100.0)),
        }
    return _indicator_values(date.today(), variety_id, region_id)


def matrix_from_series(
    series: pd.Series,
    indicators: pd.DataFrame | None = None,
    variety_id: int = 1,
    region_id: int = 1,
    last_indicators: dict[str, float] | None = None,
) -> dict[str, Any]:
    """由内存价格序列构造训练矩阵（供回测滚动重训复用，不再查库）。"""
    frame = _feature_frame(series, indicators, variety_id, region_id)
    core = ["lag1", "lag7", "lag14", "lag30", "roll_mean_7", "roll_mean_30"]
    usable = frame.dropna(subset=core + ["price"]) if len(frame) else frame
    usable = usable[usable["price"] > 0]
    if len(usable) == 0:
        return {
            "frame": frame,
            "X": np.empty((0, len(GBR_FEATURES))),
            "y": np.empty(0),
            "dates": pd.DatetimeIndex([]),
        }
    X = usable[list(GBR_FEATURES)].to_numpy(dtype=float)
    # 非核心特征若仍有缺失，用列中位数兜底，避免 sklearn 报错
    if np.isnan(X).any():
        medians = np.nanmedian(X, axis=0)
        medians = np.where(np.isnan(medians), 0.0, medians)
        nan_mask = np.isnan(X)
        X[nan_mask] = np.take(medians, np.where(nan_mask)[1])
    y = np.log(usable["price"].to_numpy(dtype=float))
    return {
        "frame": frame,
        "X": X,
        "y": y,
        "dates": usable.index,
        "last_indicators": last_indicators
        if last_indicators is not None
        else _last_indicator_row(indicators, variety_id, region_id),
    }


def build_training_matrix(
    db: Session,
    variety_id: int,
    region_id: int,
    market_type: str | None = DEFAULT_MARKET_TYPE,
) -> dict[str, Any]:
    """构造训练矩阵。

    返回 {series, frame, X, y, dates, feature_columns, labels, indicators, last_indicators}；
    无数据时 X 为空数组而不是抛异常（接口侧返回 4001/空结果）。
    """
    raw = load_price_series(db, variety_id, region_id, market_type=market_type)
    series = prepare_series(raw)
    indicators = load_indicator_frame(db, variety_id, region_id)
    last_indicators = _last_indicator_row(indicators, variety_id, region_id)
    base = matrix_from_series(series, indicators, variety_id, region_id, last_indicators)
    return {
        "series": series,
        "frame": base["frame"],
        "X": base["X"],
        "y": base["y"],
        "dates": base["dates"],
        "feature_columns": list(GBR_FEATURES),
        "labels": {k: feature_label(k) for k in GBR_FEATURES},
        "indicators": indicators,
        "last_indicators": last_indicators,
    }


# ---------------------------- 单行特征（递归预测） ----------------------------

def build_feature_row(
    history: pd.Series,
    target_date: date | pd.Timestamp,
    indicators: pd.DataFrame | None = None,
    variety_id: int = 1,
    region_id: int = 1,
    last_indicators: dict[str, float] | None = None,
) -> dict[str, float]:
    """基于截至 target_date 前一日的已知价格，构造该日预测特征行。

    history 可包含已预测出来的价格（索引为连续日期）；缺失的远期滞后项按口径兜底。
    """
    t = pd.Timestamp(target_date).normalize()
    hist = history[history.index < t]
    if len(hist) == 0:
        raise ValueError("历史价格为空，无法构造特征")
    hist = hist.sort_index()

    def _get_lag(n: int, fallback: float) -> float:
        ts = t - pd.Timedelta(days=n)
        val = hist.get(ts, np.nan)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return fallback
        try:
            return float(val)
        except (TypeError, ValueError):
            return fallback

    last = float(hist.iloc[-1])
    lag1 = _get_lag(1, last)
    lag7 = _get_lag(7, lag1)
    lag14 = _get_lag(14, lag7)
    lag30 = _get_lag(30, lag14)
    lag365 = _get_lag(365, lag30)

    tail = {n: float(hist.iloc[-n:].mean()) for n in (7, 30) if len(hist) >= 1}
    roll_mean_7 = _get_lag(0, last) if False else float(hist.iloc[-7:].mean())
    roll_mean_30 = float(hist.iloc[-30:].mean())
    roll_std_7 = float(hist.iloc[-7:].std(ddof=0)) if len(hist) >= 2 else 0.0
    roll_std_30 = float(hist.iloc[-30:].std(ddof=0)) if len(hist) >= 2 else 0.0
    roll_std_7 = 0.0 if math.isnan(roll_std_7) else roll_std_7
    roll_std_30 = 0.0 if math.isnan(roll_std_30) else roll_std_30

    d = t.date()
    doy = float(t.dayofyear)
    yoy = (lag1 / lag365 - 1.0) * 100.0 if lag365 else 0.0
    mom = (lag1 / lag30 - 1.0) * 100.0 if lag30 else 0.0

    if len(hist) >= 8:
        rets = hist.iloc[-31:].pct_change()
        vol = float(rets.std(ddof=0)) * math.sqrt(365.0) * 100.0
        if math.isnan(vol):
            vol = 0.0
    else:
        vol = 0.0
    trailing_mean = float(hist.iloc[-365:].mean())
    seasonal_index = (lag1 / trailing_mean * 100.0) if trailing_mean else 100.0

    if indicators is not None and not indicators.empty and t in indicators.index:
        row = indicators.loc[t]
        cost = float(row.get("cost_index", 100.0))
        freight = float(row.get("freight_index", 100.0))
        weather = float(row.get("weather_score", 100.0))
        holiday = float(row.get("holiday_flag", holiday_flag(d)))
    else:
        base = last_indicators or _indicator_values(d, variety_id, region_id)
        cost = float(base.get("cost_index", 100.0))
        freight = float(base.get("freight_index", 100.0))
        weather = float(base.get("weather_score", 100.0))
        holiday = float(holiday_flag(d))

    return {
        "lag1": lag1,
        "lag7": lag7,
        "lag14": lag14,
        "lag30": lag30,
        "lag365": lag365,
        "roll_mean_7": roll_mean_7,
        "roll_mean_30": roll_mean_30,
        "roll_std_7": roll_std_7,
        "roll_std_30": roll_std_30,
        "sin_doy": math.sin(2 * math.pi * doy / 365.25),
        "cos_doy": math.cos(2 * math.pi * doy / 365.25),
        "sin_doy2": math.sin(4 * math.pi * doy / 365.25),
        "cos_doy2": math.cos(4 * math.pi * doy / 365.25),
        "weekday": float(t.weekday()),
        "holiday": holiday,
        "yoy": yoy,
        "mom": mom,
        "cost_index": cost,
        "freight_index": freight,
        "weather_score": weather,
        "volatility": vol,
        "seasonal_index": seasonal_index,
    }


# ---------------------------- FeatureRecord 补算 ----------------------------

def _combo_list(db: Session) -> list[tuple[int, int]]:
    """所有启用品种×启用地区的组合（排序稳定）。"""
    varieties = db.execute(select(Variety.id).where(Variety.enabled.is_(True)).order_by(Variety.id)).scalars().all()
    regions = db.execute(select(Region.id).where(Region.enabled.is_(True)).order_by(Region.id)).scalars().all()
    return [(int(v), int(r)) for v in varieties for r in regions]


def ensure_feature_records(db: Session, days: int = 30, commit: bool = True) -> int:
    """补算最近 days 天的特征快照（同比/环比/波动率/季节指数/指数类特征）。

    已存在的 (variety_id, region_id, calc_date) 不重复插入；返回新增行数。
    无价格数据时直接返回 0（不抛异常）。
    """
    days = max(1, min(400, int(days or 30)))
    today = date.today()
    start = today - timedelta(days=days - 1)
    combos = _combo_list(db)
    if not combos:
        return 0

    # 窗口前 400 天至今天的价格（一次取回，避免逐日查询）
    lookback_start = start - timedelta(days=400)
    rows = db.execute(
        select(
            PriceRecord.variety_id,
            PriceRecord.region_id,
            PriceRecord.price_date,
            PriceRecord.price,
        )
        .where(PriceRecord.variety_id.in_([c[0] for c in combos]))
        .where(PriceRecord.region_id.in_([c[1] for c in combos]))
        .where(PriceRecord.market_type == DEFAULT_MARKET_TYPE)
        .where(PriceRecord.price_date >= lookback_start)
        .where(PriceRecord.price_date <= today)
    ).all()
    if not rows:
        return 0

    grouped: dict[tuple[int, int], dict[date, float]] = {}
    for variety_id, region_id, price_date, price in rows:
        if price is None:
            continue
        grouped.setdefault((int(variety_id), int(region_id)), {})[price_date] = float(price)

    existing = {
        (int(v), int(r), d)
        for v, r, d in db.execute(
            select(FeatureRecord.variety_id, FeatureRecord.region_id, FeatureRecord.calc_date)
            .where(FeatureRecord.calc_date >= start)
            .where(FeatureRecord.calc_date <= today)
        ).all()
    }
    existing_indicators = {
        (int(r.variety_id), int(r.region_id), r.calc_date): r
        for r in db.execute(
            select(FeatureRecord)
            .where(FeatureRecord.variety_id.in_([c[0] for c in combos]))
            .where(FeatureRecord.region_id.in_([c[1] for c in combos]))
        ).scalars().all()
    }

    inserted = 0
    for variety_id, region_id in combos:
        points = grouped.get((variety_id, region_id))
        if not points:
            continue
        raw = pd.Series(points).sort_index()
        s = prepare_series(raw)
        if s.empty:
            continue
        win = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(today))]
        if win.empty:
            continue

        for ts, price in win.items():
            calc_date = ts.date()
            price = float(price)
            prev_year = s.get(pd.Timestamp(calc_date - timedelta(days=365)), np.nan)
            prev_month = s.get(pd.Timestamp(calc_date - timedelta(days=30)), np.nan)
            history = s[s.index <= ts]
            vol = float(history.pct_change().iloc[-30:].std(ddof=0)) * math.sqrt(365.0) * 100.0
            if math.isnan(vol):
                vol = 0.0
            centered = s.rolling(365, center=True, min_periods=30).mean()
            base = centered.get(ts, np.nan)
            seasonal_index = float(price / base * 100.0) if base and not math.isnan(base) else 100.0
            yoy = float((price / prev_year - 1.0) * 100.0) if prev_year and not math.isnan(prev_year) else 0.0
            mom = float((price / prev_month - 1.0) * 100.0) if prev_month and not math.isnan(prev_month) else 0.0
            idx_vals = _indicator_values(calc_date, variety_id, region_id)

            key = (variety_id, region_id, calc_date)
            if key in existing:
                # 已有行只补零值字段，不覆盖种子数据里的业务值
                record = existing_indicators.get(key)
                if record is not None:
                    changed = False
                    if not record.yoy_pct:
                        record.yoy_pct = round(yoy, 4)
                        changed = True
                    if not record.mom_pct:
                        record.mom_pct = round(mom, 4)
                        changed = True
                    if not record.volatility_30d:
                        record.volatility_30d = round(vol, 4)
                        changed = True
                    if not record.seasonal_index:
                        record.seasonal_index = round(seasonal_index, 4)
                        changed = True
                    if not record.cost_index:
                        record.cost_index = idx_vals["cost_index"]
                        changed = True
                    if not record.freight_index:
                        record.freight_index = idx_vals["freight_index"]
                        changed = True
                    if not record.weather_score:
                        record.weather_score = idx_vals["weather_score"]
                        changed = True
                    if changed:
                        db.add(record)
                continue
            record = FeatureRecord(
                variety_id=variety_id,
                region_id=region_id,
                calc_date=calc_date,
                yoy_pct=round(yoy, 4),
                mom_pct=round(mom, 4),
                volatility_30d=round(vol, 4),
                seasonal_index=round(seasonal_index, 4),
                cost_index=idx_vals["cost_index"],
                freight_index=idx_vals["freight_index"],
                weather_score=idx_vals["weather_score"],
                holiday_flag=holiday_flag(calc_date),
            )
            db.add(record)
            existing.add(key)
            inserted += 1

    if commit:
        db.commit()
    else:
        db.flush()
    return inserted
