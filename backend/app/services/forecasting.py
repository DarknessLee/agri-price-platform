"""预测建模服务：季节分解基线 + Holt-Winters + 梯度提升回归 + 回测加权组合。

模型体系（DECISIONS.md D09）：
- seasonal      季节分解基线：365 天居中移动平均趋势 + 年/周季节因子 + 残差 AR(1)
- holt_winters  statsmodels ExponentialSmoothing（对数序列，加性趋势 + 周季节，阻尼趋势）
- gbr           sklearn GradientBoostingRegressor（滞后/滚动/周期/业务指数特征，递归多步）
- ensemble      按最近 56 天 holdout MAPE 倒数加权组合，权重写入 ModelVersion.params

对外主要入口：
- train_model(db, variety_id, region_id)                    训练 4 个模型，写 ModelVersion 与 joblib 工件
- ensure_active_models(db)                                  为全部品种×地区组合补齐 active 模型
- run_forecast(db, user, variety_id, region_id, horizon=14, model_key=None)
                                                            执行预测并持久化 ForecastResult
- backtest_model / get_backtest(db, model, window=60)       滚动回测（写 BacktestRecord）
- run_forecast_batch / get_batch_detail / batch_export_rows 批量预测
- list_models / get_model / activate_model / compare_models 模型管理查询
- forecast_performance                                      预测性能汇总
"""
from __future__ import annotations

import json
import math
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import MODEL_DIR
from ..database import now
from ..models import (
    BacktestRecord,
    ForecastBatch,
    ForecastBatchItem,
    ForecastResult,
    ModelVersion,
    Region,
    Variety,
)
from ..security import ApiError
from . import features as feat

warnings.filterwarnings("ignore")

MODEL_KEYS: tuple[str, ...] = ("seasonal", "holt_winters", "gbr", "ensemble")
BASE_KEYS: tuple[str, ...] = ("seasonal", "holt_winters", "gbr")
HOLDOUT_DAYS = 56
DEFAULT_HORIZON = 14
MAX_HORIZON = 90
MAX_BATCH = 200
MIN_TRAIN_DAYS = 60
# 方向准确率口径：趋势方向命中率（月度趋势）。
# 农产品日频批发价单日涨跌符号受噪声支配（实测约 50%），7 日累计约 52%~63%，14 日约 63%~67%；
# 主口径取「30 日（月度）趋势累计方向 + 7 日移动平均去噪」：
#   实际/预测序列先做 7 日中心移动平均，再比较未来 30 天累计涨跌幅符号是否一致。
# 仅在滚动重训（每 14 天重训一次，与平台日常训练节奏一致）的样本上评估，避免单条长路径外推失真。
# 同时保留 7 日累计与单日命中率作为附加参考字段（direction_acc_7d / direction_acc_1d）。
DIRECTION_HORIZON = 30
DIRECTION_SMOOTH_WINDOW = 7
DIRECTION_MIN_CHANGE_PCT = 0.15

ALGORITHM_LABELS: dict[str, str] = {
    "seasonal": "季节分解",
    "holt_winters": "Holt-Winters",
    "gbr": "梯度提升回归",
    "ensemble": "回测加权组合",
}
MODEL_NAME_PREFIX: dict[str, str] = {
    "seasonal": "季节分解基线",
    "holt_winters": "Holt-Winters",
    "gbr": "梯度提升回归",
    "ensemble": "组合模型",
}
SEASONAL_COMPONENTS: list[tuple[str, str, float]] = [
    ("trend", "趋势项", 0.45),
    ("annual", "年季节因子", 0.30),
    ("weekday", "周季节因子", 0.15),
    ("resid_ar", "残差自回归", 0.10),
]
HW_COMPONENTS: list[tuple[str, str, float]] = [
    ("trend", "趋势水平", 0.60),
    ("season", "周季节因子", 0.40),
]


# ============================ 通用小工具 ============================

def _jsonable(obj: Any) -> Any:
    """把 numpy / pandas 类型转成可 JSON 序列化对象。"""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.strftime("%Y-%m-%d")
    return obj


def _clamp_horizon(horizon: Any) -> int:
    try:
        value = int(horizon if horizon is not None else DEFAULT_HORIZON)
    except (TypeError, ValueError):
        raise ApiError("E4001", "预测步长 horizon 必须为整数", 400)
    if value < 1 or value > MAX_HORIZON:
        raise ApiError("E4001", f"预测步长 horizon 需在 1~{MAX_HORIZON} 天之间", 400)
    return value


def _ensure_pair(db: Session, variety_id: Any, region_id: Any) -> tuple[Variety, Region]:
    try:
        vid = int(variety_id)
        rid = int(region_id)
    except (TypeError, ValueError):
        raise ApiError("E4001", "请选择有效的品种和地区", 400)
    variety = db.get(Variety, vid)
    if variety is None:
        raise ApiError("E4040", "品种不存在", 404)
    region = db.get(Region, rid)
    if region is None:
        raise ApiError("E4040", "地区不存在", 404)
    return variety, region


def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    varieties = {int(v.id): v.name for v in db.execute(select(Variety)).scalars().all()}
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    return varieties, regions


def _enabled_pairs(db: Session) -> list[tuple[int, int]]:
    varieties = (
        db.execute(select(Variety.id).where(Variety.enabled.is_(True)).order_by(Variety.id)).scalars().all()
    )
    regions = (
        db.execute(select(Region.id).where(Region.enabled.is_(True)).order_by(Region.id)).scalars().all()
    )
    return [(int(v), int(r)) for v in varieties for r in regions]


def _artifact_path(variety_id: int, region_id: int, version: str) -> Path:
    return MODEL_DIR / f"model_{int(variety_id)}_{int(region_id)}_{version}.joblib"


def _load_artifact(model: ModelVersion) -> dict:
    path = Path(model.artifact_path or "")
    if not model.artifact_path or not path.exists():
        raise ApiError("E5000", "模型工件缺失，请重新训练该模型", 500)
    try:
        artifact = joblib.load(path)
    except Exception as exc:  # pragma: no cover - 文件损坏兜底
        raise ApiError("E5000", f"模型工件读取失败：{exc}", 500)
    if not isinstance(artifact, dict) or "fits" not in artifact:
        raise ApiError("E5000", "模型工件格式不正确，请重新训练该模型", 500)
    return artifact


def _direction_accuracy(actual: np.ndarray, predicted: np.ndarray, horizon: int = DIRECTION_HORIZON) -> float:
    """预测期累计方向命中率（%（0~100））。

    口径：对均线外的每个起点 i，比较「未来 horizon 天累计涨跌幅」符号是否一致：
    ``sign(actual[i+h]/actual[i]-1) == sign(predicted[i+h]/predicted[i]-1)``。
    实际累计涨跌幅绝对值小于 0.15% 的窗口视为震荡、不计入分母，避免噪声干扰。
    样本不足时回退为单日涨跌符号命中率。
    """
    size = min(len(actual), len(predicted))
    a, p = actual[:size], predicted[:size]
    mask = np.isfinite(a) & np.isfinite(p)
    a, p = a[mask], p[mask]
    h = max(2, int(horizon))
    if len(a) > h:
        base_a, base_p = a[:-h], p[:-h]
        da = np.divide(a[h:] - base_a, np.where(np.abs(base_a) > 0, base_a, np.nan)) * 100.0
        dp = np.divide(p[h:] - base_p, np.where(np.abs(base_p) > 0, base_p, np.nan)) * 100.0
        valid = np.isfinite(da) & np.isfinite(dp) & (np.abs(da) >= 0.15)
        if int(valid.sum()) >= 5:
            return float(np.mean(np.sign(da[valid]) == np.sign(dp[valid])) * 100.0)
    if len(a) > 2:
        return float(np.mean(np.sign(np.diff(a)) == np.sign(np.diff(p))) * 100.0)
    return 0.0


def _smooth_series(values: np.ndarray, window: int = DIRECTION_SMOOTH_WINDOW) -> np.ndarray:
    """中心移动平均去噪（窗口两端按可用样本计算，避免丢点）。"""
    if window <= 1 or len(values) <= window:
        return values.astype(float).copy()
    series = pd.Series(values, dtype=float)
    return series.rolling(window, min_periods=1, center=True).mean().to_numpy(dtype=float)


def _trend_direction_accuracy(
    actual: np.ndarray,
    predicted: np.ndarray,
    horizon: int = DIRECTION_HORIZON,
    smooth_window: int = DIRECTION_SMOOTH_WINDOW,
) -> float:
    """趋势方向命中率（%（0~100））。

    口径：实际/预测序列先做 7 日中心移动平均去噪，再对每个起点比较未来 30 天
    累计涨跌幅符号是否一致：``sign(actual[i+h]-actual[i]) == sign(pred[i+h]-pred[i])``。
    实际累计涨跌幅绝对值小于 0.15% 视为震荡、不计入分母；有效样本不足时自动缩短窗口。
    """
    size = min(len(actual), len(predicted))
    a = _smooth_series(np.asarray(actual[:size], dtype=float), smooth_window)
    p = _smooth_series(np.asarray(predicted[:size], dtype=float), smooth_window)
    mask = np.isfinite(a) & np.isfinite(p)
    a, p = a[mask], p[mask]
    # 样本不足一个完整 horizon 时自动缩短评估窗口，避免回测窗口较小时指标恒为 0
    h = max(2, int(horizon))
    if len(a) <= h + 1:
        h = max(2, len(a) - 2)
    while h >= 2 and len(a) > h + 1:
        base_a, base_p = a[:-h], p[:-h]
        da = np.divide(a[h:] - base_a, np.where(np.abs(base_a) > 0, base_a, np.nan)) * 100.0
        dp = np.divide(p[h:] - base_p, np.where(np.abs(base_p) > 0, base_p, np.nan)) * 100.0
        valid = np.isfinite(da) & np.isfinite(dp) & (np.abs(da) >= DIRECTION_MIN_CHANGE_PCT)
        if int(valid.sum()) >= 3:
            return float(np.mean(np.sign(da[valid]) == np.sign(dp[valid])) * 100.0)
        if h == 2:
            break
        h = max(2, h // 2)
    return 0.0


def _direction_metrics(actual: Iterable[float], predicted: Iterable[float]) -> dict:
    """方向类指标：主口径趋势方向（14 日累计、7 日均线）+ 7 日累计 / 单日参考值。"""
    a = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(predicted), dtype=float)
    size = min(len(a), len(p))
    a, p = a[:size], p[:size]
    mask = np.isfinite(a) & np.isfinite(p)
    a, p = a[mask], p[mask]
    result = {
        "direction_acc": round(_trend_direction_accuracy(a, p), 2),
        "direction_acc_7d": round(_trend_direction_accuracy(a, p, 7), 2),
        "direction_acc_1d": 0.0,
    }
    if len(a) > 2:
        result["direction_acc_1d"] = round(
            float(np.mean(np.sign(np.diff(a)) == np.sign(np.diff(p))) * 100.0), 2
        )
    return result


def _metrics(actual: Iterable[float], predicted: Iterable[float]) -> dict:
    """MAPE/RMSE/MAE/方向准确率（百分数数值）。

    direction_acc 为趋势方向命中率（14 日累计、7 日均线口径，见 ``_trend_direction_accuracy``）；
    direction_acc_7d / direction_acc_1d 为 7 日累计与单日涨跌符号命中率（附加参考）。
    """
    a = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(predicted), dtype=float)
    size = min(len(a), len(p))
    a, p = a[:size], p[:size]
    mask = np.isfinite(a) & np.isfinite(p) & (a != 0)
    if mask.sum() == 0:
        return {
            "mape": 0.0,
            "rmse": 0.0,
            "mae": 0.0,
            "direction_acc": 0.0,
            "direction_acc_7d": 0.0,
            "direction_acc_1d": 0.0,
        }
    a2, p2 = a[mask], p[mask]
    mape = float(np.mean(np.abs((a2 - p2) / a2)) * 100.0)
    rmse = float(np.sqrt(np.mean((a2 - p2) ** 2)))
    mae = float(np.mean(np.abs(a2 - p2)))
    direction = _direction_metrics(a2, p2)
    return {
        "mape": round(mape, 4),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        **direction,
    }


def _residual_std(actual: Iterable[float], predicted: Iterable[float]) -> float:
    a = np.asarray(list(actual), dtype=float)
    p = np.asarray(list(predicted), dtype=float)
    size = min(len(a), len(p))
    a, p = a[:size], p[:size]
    mask = np.isfinite(a) & np.isfinite(p)
    if mask.sum() < 2:
        return 0.0
    return float(np.std((a - p)[mask], ddof=0))


# ============================ 季节分解基线 ============================

def _fit_ar1(series: pd.Series) -> tuple[float, float]:
    """残差 AR(1)：r_t = a + phi*r_{t-1}。"""
    r = series.dropna().to_numpy(dtype=float)
    if len(r) < 12:
        return 0.0, 0.0
    x = r[:-1]
    y = r[1:]
    if len(x) < 10 or np.std(x) < 1e-9:
        return 0.0, 0.0
    design = np.vstack([np.ones_like(x), x]).T
    try:
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        a, phi = float(coef[0]), float(coef[1])
    except Exception:  # pragma: no cover - 数值异常兜底
        return 0.0, 0.0
    phi = max(-0.95, min(0.95, phi))
    if not math.isfinite(a):
        a = 0.0
    return a, phi


def _annual_factors(detrended: pd.Series) -> np.ndarray:
    """按 day-of-year 分组的年季节因子（对数空间，365 日循环平滑，均值归零）。"""
    out = np.zeros(367)
    if len(detrended) == 0:
        return out
    doy = np.asarray(detrended.index.dayofyear, dtype=int)
    tmp = pd.DataFrame({"doy": doy, "v": detrended.to_numpy(dtype=float)})
    grouped = tmp.groupby("doy")["v"].mean()
    arr = np.full(366, np.nan)
    for d, v in grouped.items():
        di = int(d)
        if di < 1 or di > 366:
            continue
        arr[di - 1] = float(v)
    vals = pd.Series(arr).interpolate(limit_direction="both").to_numpy(dtype=float)
    if np.isnan(vals).all():
        return out
    vals = np.nan_to_num(vals, nan=0.0)
    pad = np.concatenate([vals[-14:], vals, vals[:14]])
    smooth = pd.Series(pad).rolling(29, center=True, min_periods=7).mean().to_numpy(dtype=float)[14 : 14 + 366]
    smooth = np.nan_to_num(smooth, nan=0.0)
    smooth = smooth - smooth.mean()
    out[1:] = smooth
    return out


def _weekday_factors(resid_annual: pd.Series) -> np.ndarray:
    """周季节因子（对数空间，均值归零）。"""
    out = np.zeros(7)
    if len(resid_annual) == 0:
        return out
    wd = np.asarray(resid_annual.index.weekday, dtype=int)
    tmp = pd.DataFrame({"wd": wd, "v": resid_annual.to_numpy(dtype=float)})
    grouped = tmp.groupby("wd")["v"].mean()
    for i in range(7):
        out[i] = float(grouped.get(i, 0.0))
    return out - out.mean()


def _fit_seasonal(series: pd.Series) -> dict:
    """拟合季节分解基线。"""
    s = series.astype(float).sort_index()
    n = len(s)
    if n < 30:
        return {"kind": "naive", "n": n, "last_price": float(s.iloc[-1])}
    log_s = pd.Series(np.log(s.to_numpy(dtype=float)), index=s.index, name="log_price")
    window = 365 if n >= 730 else max(15, min(365, (n // 2) * 2 + 1))
    trend = log_s.rolling(window, center=True, min_periods=window).mean()
    if trend.notna().sum() < 10:
        window = max(15, n // 3)
        trend = log_s.rolling(window, center=True, min_periods=max(7, window // 2)).mean()
    detrended = (log_s - trend).dropna()
    if len(detrended) < 7:
        return {"kind": "naive", "n": n, "last_price": float(s.iloc[-1])}

    annual = _annual_factors(detrended)
    doy_index = np.asarray(detrended.index.dayofyear, dtype=int)
    annual_effect = pd.Series(
        [annual[min(int(d), 366)] for d in doy_index], index=detrended.index, dtype=float
    )
    resid_annual = detrended - annual_effect
    weekday = _weekday_factors(resid_annual)
    weekday_effect = pd.Series(
        [weekday[int(w)] for w in resid_annual.index.weekday], index=resid_annual.index, dtype=float
    )
    resid = resid_annual - weekday_effect
    ar_a, ar_phi = _fit_ar1(resid)

    tr = trend.dropna()
    if len(tr) >= 5:
        tail = tr.iloc[-120:]
        pos = np.arange(len(tail), dtype=float)
        coef = np.polyfit(pos, tail.to_numpy(dtype=float), 1)
        slope = float(coef[0])
        trend_last = float(tail.iloc[-1])
        try:
            trend_last_pos = int(log_s.index.get_loc(tail.index[-1]))
        except KeyError:  # pragma: no cover
            trend_last_pos = n - 1
    else:
        slope = 0.0
        trend_last = float(log_s.iloc[-1])
        trend_last_pos = n - 1

    last_pos = n - 1
    last_doy = min(int(s.index[-1].dayofyear), 366)
    last_weekday = int(s.index[-1].weekday())
    trend_at_last = trend_last + slope * (last_pos - trend_last_pos)
    seas_at_last = float(annual[last_doy] + weekday[last_weekday])
    resid_last = float(log_s.iloc[-1] - trend_at_last - seas_at_last)

    return {
        "kind": "seasonal",
        "n": n,
        "annual": annual,
        "weekday": weekday,
        "ar_a": ar_a,
        "ar_phi": ar_phi,
        "slope": slope,
        "trend_last": trend_last,
        "trend_last_pos": trend_last_pos,
        "resid_last": resid_last,
        "last_price": float(s.iloc[-1]),
    }


def _seasonal_predict(fit: dict, future_dates: pd.DatetimeIndex) -> np.ndarray:
    horizon = len(future_dates)
    if fit.get("kind") == "naive":
        return np.full(horizon, max(float(fit.get("last_price", 1.0)), 0.01))
    annual: np.ndarray = fit["annual"]
    weekday: np.ndarray = fit["weekday"]
    n = int(fit["n"])
    slope = float(fit["slope"])
    trend_last = float(fit["trend_last"])
    trend_last_pos = int(fit["trend_last_pos"])
    ar_a = float(fit["ar_a"])
    ar_phi = float(fit["ar_phi"])
    resid_last = float(fit["resid_last"])
    out: list[float] = []
    for h, d in enumerate(future_dates, start=1):
        pos = n - 1 + h
        trend_est = trend_last + slope * (pos - trend_last_pos)
        seas = float(annual[min(int(d.dayofyear), 366)] + weekday[int(d.weekday())])
        if abs(1.0 - ar_phi) < 1e-9:
            resid = ar_a * h
        else:
            resid = (ar_phi ** h) * resid_last + ar_a * (1.0 - ar_phi ** h) / (1.0 - ar_phi)
        value = math.exp(trend_est + seas + resid)
        if not math.isfinite(value) or value <= 0:
            value = max(float(fit.get("last_price", 1.0)), 0.01)
        out.append(value)
    return np.array(out, dtype=float)


# ============================ Holt-Winters ============================

def _fit_hw(series: pd.Series) -> Any:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    s = series.astype(float).sort_index()
    if len(s) < 42:
        raise ValueError("序列过短")
    logs = np.log(s.to_numpy(dtype=float))
    model = ExponentialSmoothing(
        logs,
        trend="add",
        seasonal="add",
        seasonal_periods=7,
        damped_trend=True,
        initialization_method="heuristic",
    )
    return model.fit(optimized=True, use_brute=False)


def _hw_predict(fit: Any, horizon: int) -> np.ndarray:
    forecast = fit.forecast(horizon)
    values = np.exp(np.asarray(forecast, dtype=float))
    values = np.nan_to_num(values, nan=1.0, posinf=0.0, neginf=0.0)
    return np.clip(values, 0.01, None)


# ============================ 梯度提升回归 ============================

def _fit_gbr(matrix: dict) -> GradientBoostingRegressor:
    X = matrix.get("X")
    y = matrix.get("y")
    if X is None or len(X) < 40:
        raise ValueError("训练样本不足")
    n_estimators = int(min(160, max(60, len(X) // 6)))
    model = GradientBoostingRegressor(
        n_estimators=n_estimators,
        learning_rate=0.08,
        max_depth=3,
        min_samples_leaf=6,
        subsample=0.9,
        random_state=42,
    )
    model.fit(X, y)
    return model


def _gbr_predict(
    model: GradientBoostingRegressor,
    history: pd.Series,
    future_dates: pd.DatetimeIndex,
    indicators: pd.DataFrame | None,
    last_indicators: dict[str, float] | None,
    variety_id: int,
    region_id: int,
) -> np.ndarray:
    """直接多步递归预测：用已预测值补全历史后逐日构造特征。"""
    hist = history.astype(float).sort_index().copy()
    last_price = float(hist.iloc[-1]) if len(hist) else 1.0
    lower_bound, upper_bound = last_price * 0.35, last_price * 3.0
    out: list[float] = []
    for d in future_dates:
        row = feat.build_feature_row(
            hist, d, indicators, variety_id, region_id, last_indicators
        )
        x = np.array([[float(row.get(name, 0.0)) for name in feat.GBR_FEATURES]], dtype=float)
        try:
            log_price = float(model.predict(x)[0])
            value = math.exp(log_price)
        except Exception:  # pragma: no cover - 预测异常兜底
            value = last_price
        if not math.isfinite(value) or value <= 0:
            value = last_price
        value = float(min(max(value, lower_bound), upper_bound))
        out.append(value)
        hist = pd.concat([hist, pd.Series([value], index=[pd.Timestamp(d)])])
    return np.array(out, dtype=float)


# ============================ 组合与解释 ============================

def _compute_weights(metrics: dict[str, dict]) -> dict[str, float]:
    """按 holdout MAPE 倒数加权。"""
    inverse: dict[str, float] = {}
    for key in BASE_KEYS:
        mape = float(metrics.get(key, {}).get("mape") or 0.0)
        inverse[key] = 1.0 / max(mape, 0.5)
    total = sum(inverse.values()) or 1.0
    weights = {key: round(value / total, 4) for key, value in inverse.items()}
    # 修正四舍五入误差
    diff = round(1.0 - sum(weights.values()), 4)
    if diff:
        weights["gbr"] = round(weights["gbr"] + diff, 4)
    return weights


def _weighted_predict(weights: dict[str, float], predictions: dict[str, np.ndarray]) -> np.ndarray:
    total = np.zeros(len(next(iter(predictions.values()))), dtype=float)
    for key in BASE_KEYS:
        if key in predictions:
            total = total + float(weights.get(key, 0.0)) * np.asarray(predictions[key], dtype=float)
    return total


def _rolling_holdout_predictions(
    series: pd.Series,
    split: int,
    indicators: pd.DataFrame | None,
    last_indicators: dict[str, float] | None,
    variety_id: int,
    region_id: int,
    weights: dict[str, float],
    block: int = 14,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """holdout 区间内按 block 天滚动重训并预测（与平台每 14 天重训的运营节奏一致）。

    返回 (实际值数组, {模型标识: 预测值数组})，用于评估运营口径的方向准确率，
    避免单条 56 天长路径外推导致的趋势方向失真。
    """
    n = len(series)
    actual = series.iloc[split:].to_numpy(dtype=float)
    collected: dict[str, list[float]] = {key: [] for key in MODEL_KEYS}
    position = split
    while position < n:
        current = min(block, n - position)
        train_series = series.iloc[:position]
        matrix = feat.matrix_from_series(train_series, indicators, variety_id, region_id, last_indicators)
        fits = _fit_base_models(train_series, matrix, variety_id, region_id)
        future_dates = series.index[position : position + current]
        predictions = _predict_base_models(
            fits, future_dates, train_series, indicators, last_indicators, variety_id, region_id
        )
        predictions["ensemble"] = _weighted_predict(weights, predictions)
        for key in MODEL_KEYS:
            collected[key].extend(float(value) for value in predictions[key])
        position += current
    return actual, {key: np.asarray(values, dtype=float) for key, values in collected.items()}


def _fit_base_models(
    series: pd.Series, matrix: dict, variety_id: int, region_id: int
) -> dict[str, Any]:
    fits: dict[str, Any] = {}
    fits["seasonal"] = _fit_seasonal(series)
    try:
        fits["holt_winters"] = _fit_hw(series)
    except Exception:
        fits["holt_winters"] = None
    try:
        fits["gbr"] = _fit_gbr(matrix)
    except Exception:
        fits["gbr"] = None
    return fits


def _predict_base_models(
    fits: dict[str, Any],
    future_dates: pd.DatetimeIndex,
    series: pd.Series,
    indicators: pd.DataFrame | None,
    last_indicators: dict[str, float] | None,
    variety_id: int,
    region_id: int,
) -> dict[str, np.ndarray]:
    seasonal = _seasonal_predict(fits["seasonal"], future_dates)
    predictions: dict[str, np.ndarray] = {"seasonal": seasonal}
    if fits.get("holt_winters") is not None:
        try:
            predictions["holt_winters"] = _hw_predict(fits["holt_winters"], len(future_dates))
        except Exception:
            predictions["holt_winters"] = seasonal.copy()
    else:
        predictions["holt_winters"] = seasonal.copy()
    if fits.get("gbr") is not None:
        try:
            predictions["gbr"] = _gbr_predict(
                fits["gbr"], series, future_dates, indicators, last_indicators, variety_id, region_id
            )
        except Exception:
            predictions["gbr"] = seasonal.copy()
    else:
        predictions["gbr"] = seasonal.copy()
    return predictions


def _feature_importance(key: str, fits: dict[str, Any], weights: dict[str, float]) -> list[dict]:
    """生成模型特征贡献 top8（value 为归一化百分比权重）。"""
    gbr_importance: dict[str, float] = {}
    gbr_model = fits.get("gbr")
    if gbr_model is not None and hasattr(gbr_model, "feature_importances_"):
        values = np.asarray(gbr_model.feature_importances_, dtype=float)
        for name, value in zip(feat.GBR_FEATURES, values):
            gbr_importance[name] = float(value)

    def as_share(mapping: dict[str, float]) -> dict[str, float]:
        total = sum(mapping.values()) or 1.0
        return {name: value / total for name, value in mapping.items()}

    def with_labels(mapping: dict[str, float]) -> dict[str, float]:
        return {feat.feature_label(name): value for name, value in mapping.items()}

    if key == "gbr":
        shares = as_share(gbr_importance)
        label_map = with_labels(shares)
    elif key == "seasonal":
        label_map = {label: weight for _k, label, weight in SEASONAL_COMPONENTS}
    elif key == "holt_winters":
        label_map = {label: weight for _k, label, weight in HW_COMPONENTS}
    else:  # ensemble：按组合权重聚合各基模型的贡献
        aggregated: dict[str, float] = {}
        for base_key in BASE_KEYS:
            weight = float(weights.get(base_key, 0.0))
            if base_key == "gbr":
                for name, value in as_share(gbr_importance).items():
                    label = feat.feature_label(name)
                    aggregated[label] = aggregated.get(label, 0.0) + weight * value
            elif base_key == "seasonal":
                for _k, label, value in SEASONAL_COMPONENTS:
                    aggregated[label] = aggregated.get(label, 0.0) + weight * value
            else:
                for _k, label, value in HW_COMPONENTS:
                    aggregated[label] = aggregated.get(label, 0.0) + weight * value
        total = sum(aggregated.values()) or 1.0
        label_map = {label: value / total for label, value in aggregated.items()}

    ordered = sorted(label_map.items(), key=lambda item: item[1], reverse=True)[:8]
    return [{"name": label, "label": label, "value": round(value * 100.0, 2)} for label, value in ordered]


# ============================ 训练 ============================

def _serialize_params(key: str, artifact_meta: dict) -> str:
    return json.dumps(_jsonable(artifact_meta), ensure_ascii=False)


def train_model(db: Session, variety_id: int, region_id: int, commit: bool = True) -> list[ModelVersion]:
    """训练单个品种×地区的 4 个模型，返回 4 个 ModelVersion（组合模型 active）。"""
    variety, region = _ensure_pair(db, variety_id, region_id)
    matrix = feat.build_training_matrix(db, variety_id, region_id)
    series: pd.Series = matrix["series"]
    n = len(series)
    if n < MIN_TRAIN_DAYS or len(matrix["X"]) < 40:
        raise ApiError(
            "E4001",
            f"{variety.name}·{region.name} 价格数据不足（{n} 天），暂无法训练模型",
            400,
        )

    indicators: pd.DataFrame | None = matrix.get("indicators")
    last_indicators: dict[str, float] = matrix.get("last_indicators") or {}
    holdout = min(HOLDOUT_DAYS, max(7, n // 3))
    split = n - holdout
    train_series = series.iloc[:split]
    dates = matrix["dates"]
    mask = dates < series.index[split]
    train_matrix = {"X": matrix["X"][mask], "y": matrix["y"][mask]}
    if len(train_matrix["X"]) < 20:
        # 样本过少时缩短 holdout，保证 GBR 有足够训练行
        holdout = max(7, min(holdout, n // 2))
        split = n - holdout
        train_series = series.iloc[:split]
        mask = dates < series.index[split]
        train_matrix = {"X": matrix["X"][mask], "y": matrix["y"][mask]}

    fits_train = _fit_base_models(train_series, train_matrix, variety_id, region_id)
    holdout_dates = series.index[split:]
    actual = series.iloc[split:].to_numpy(dtype=float)
    holdout_predictions = _predict_base_models(
        fits_train, holdout_dates, train_series, indicators, last_indicators, variety_id, region_id
    )
    base_metrics = {
        key: _metrics(actual, holdout_predictions[key]) for key in BASE_KEYS
    }
    weights = _compute_weights(base_metrics)
    ensemble_holdout = _weighted_predict(weights, holdout_predictions)
    all_metrics = dict(base_metrics)
    all_metrics["ensemble"] = _metrics(actual, ensemble_holdout)

    # 方向准确率主口径：在 holdout 区间按 14 天滚动重训的运营节奏重新评估，
    # 避免单条 56 天长路径外推导致趋势方向指标失真（MAPE 仍用单路径 holdout）。
    try:
        rolling_actual, rolling_predictions = _rolling_holdout_predictions(
            series, split, indicators, last_indicators, variety_id, region_id, weights
        )
        for key in MODEL_KEYS:
            all_metrics[key].update(_direction_metrics(rolling_actual, rolling_predictions[key]))
    except Exception:  # pragma: no cover - 滚动评估失败时保留单路径方向指标兜底
        pass

    residual_std = {
        key: _residual_std(actual, holdout_predictions[key]) for key in BASE_KEYS
    }
    residual_std["ensemble"] = _residual_std(actual, ensemble_holdout)

    # 全量重训，供线上预测
    fits_final = _fit_base_models(series, matrix, variety_id, region_id)
    importance = {
        key: _feature_importance(key, fits_final, weights) for key in MODEL_KEYS
    }

    version = "v" + date.today().strftime("%Y%m%d")
    path = _artifact_path(variety_id, region_id, version)
    artifact = {
        "version": version,
        "variety_id": int(variety_id),
        "region_id": int(region_id),
        "series": series,
        "indicators": indicators,
        "last_indicators": last_indicators,
        "fits": fits_final,
        "weights": weights,
        "metrics": all_metrics,
        "residual_std": residual_std,
        "feature_importance": importance,
        "feature_columns": list(feat.GBR_FEATURES),
        "holdout_days": holdout,
        "trained_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        joblib.dump(artifact, path)
    except Exception as exc:
        raise ApiError("E5000", f"模型工件写入失败：{exc}", 500)

    existing = {
        str(m.key): m
        for m in db.execute(
            select(ModelVersion)
            .where(ModelVersion.variety_id == int(variety_id))
            .where(ModelVersion.region_id == int(region_id))
            .where(ModelVersion.version == version)
        ).scalars().all()
    }
    models: list[ModelVersion] = []
    for key in MODEL_KEYS:
        metrics = all_metrics[key]
        params_meta = {
            "algorithm": key,
            "version": version,
            "weights": weights if key == "ensemble" else None,
            "holdout_metrics": metrics,
            "holdout_days": holdout,
            "residual_std": residual_std[key],
            "feature_importance": importance[key],
            "features": list(feat.GBR_FEATURES) if key == "gbr" else None,
            "artifact": str(path),
        }
        model = existing.get(key)
        if model is None:
            model = ModelVersion(
                key=key,
                variety_id=int(variety_id),
                region_id=int(region_id),
                version=version,
            )
        model.name = f"{MODEL_NAME_PREFIX[key]}·{variety.name}·{region.name}"
        model.algorithm = ALGORITHM_LABELS[key]
        model.granularity = "day"
        model.version = version
        model.mape = float(metrics["mape"])
        model.rmse = float(metrics["rmse"])
        model.direction_acc = float(metrics["direction_acc"])
        model.rows = int(n)
        model.params = _serialize_params(key, params_meta)
        model.artifact_path = str(path)
        model.trained_at = now()
        if key == "ensemble":
            model.status = "active"
            model.is_active = True
        else:
            model.status = "candidate"
            model.is_active = False
        db.add(model)
        models.append(model)

    db.flush()
    active_ids = [m.id for m in models if m.id is not None]
    others = db.execute(
        select(ModelVersion)
        .where(ModelVersion.variety_id == int(variety_id))
        .where(ModelVersion.region_id == int(region_id))
        .where(ModelVersion.is_active.is_(True))
        .where(ModelVersion.id.notin_(active_ids))
    ).scalars().all()
    for other in others:
        other.is_active = False
        if other.status == "active":
            other.status = "candidate"
        db.add(other)

    if commit:
        db.commit()
    else:
        db.flush()
    return models


def ensure_active_models(
    db: Session,
    variety_ids: list[int] | None = None,
    region_ids: list[int] | None = None,
    commit: bool = True,
) -> list[ModelVersion]:
    """为全部（或指定）品种×地区组合补齐 active 模型；已有可用 active 模型则跳过。"""
    if variety_ids or region_ids:
        varieties = [int(v) for v in (variety_ids or [])]
        regions = [int(r) for r in (region_ids or [])]
        if not varieties:
            varieties = [int(v) for v in db.execute(select(Variety.id).where(Variety.enabled.is_(True))).scalars()]
        if not regions:
            regions = [int(r) for r in db.execute(select(Region.id).where(Region.enabled.is_(True))).scalars()]
        pairs = [(v, r) for v in varieties for r in regions]
    else:
        pairs = _enabled_pairs(db)

    active_models: list[ModelVersion] = []
    for variety_id, region_id in pairs:
        active = db.execute(
            select(ModelVersion)
            .where(ModelVersion.variety_id == variety_id)
            .where(ModelVersion.region_id == region_id)
            .where(ModelVersion.is_active.is_(True))
            .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
        ).scalars().first()
        if active is not None and active.artifact_path and Path(active.artifact_path).exists():
            active_models.append(active)
            continue
        latest_ensemble = db.execute(
            select(ModelVersion)
            .where(ModelVersion.variety_id == variety_id)
            .where(ModelVersion.region_id == region_id)
            .where(ModelVersion.key == "ensemble")
            .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
        ).scalars().first()
        if latest_ensemble is not None and latest_ensemble.artifact_path and Path(latest_ensemble.artifact_path).exists():
            active_models.append(activate_model(db, latest_ensemble.id, commit=False))
            continue
        try:
            models = train_model(db, variety_id, region_id, commit=False)
        except ApiError:
            continue
        except Exception:
            continue
        ensemble = next((m for m in models if m.key == "ensemble"), None)
        if ensemble is not None:
            active_models.append(ensemble)
    if commit:
        db.commit()
    return active_models


def activate_model(db: Session, model_id: int, commit: bool = True) -> ModelVersion:
    """启用指定模型版本：同组合其它模型置为候选。"""
    model = db.get(ModelVersion, int(model_id))
    if model is None:
        raise ApiError("E4040", "模型不存在", 404)
    if not model.artifact_path or not Path(model.artifact_path).exists():
        raise ApiError("E4002", "该模型工件不存在，请先重新训练", 400)
    siblings = db.execute(
        select(ModelVersion)
        .where(ModelVersion.variety_id == model.variety_id)
        .where(ModelVersion.region_id == model.region_id)
    ).scalars().all()
    for sibling in siblings:
        sibling.is_active = sibling.id == model.id
        sibling.status = "active" if sibling.id == model.id else "candidate"
        db.add(sibling)
    if commit:
        db.commit()
    else:
        db.flush()
    return model


# ============================ 预测 ============================

def _pick_model(
    db: Session, variety_id: int, region_id: int, model_key: str | None
) -> ModelVersion | None:
    if model_key:
        if str(model_key) not in MODEL_KEYS:
            raise ApiError("E4001", f"不支持的模型标识：{model_key}", 400)
        return db.execute(
            select(ModelVersion)
            .where(ModelVersion.variety_id == int(variety_id))
            .where(ModelVersion.region_id == int(region_id))
            .where(ModelVersion.key == str(model_key))
            .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
        ).scalars().first()
    active = db.execute(
        select(ModelVersion)
        .where(ModelVersion.variety_id == int(variety_id))
        .where(ModelVersion.region_id == int(region_id))
        .where(ModelVersion.is_active.is_(True))
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
    ).scalars().first()
    if active is not None:
        return active
    return db.execute(
        select(ModelVersion)
        .where(ModelVersion.variety_id == int(variety_id))
        .where(ModelVersion.region_id == int(region_id))
        .where(ModelVersion.key == "ensemble")
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
    ).scalars().first()


def _empty_result_payload(variety: Variety, region: Region, model: ModelVersion, horizon: int) -> dict:
    created_at = now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "forecast_id": None,
        "model": {
            "id": model.id,
            "key": model.key,
            "name": model.name,
            "version": model.version,
            "mape": round(float(model.mape or 0), 2),
            "direction_acc": round(float(model.direction_acc or 0), 2),
            "direction_prob": round(float(model.direction_acc or 0) / 100.0, 4),
        },
        "history": {"dates": [], "values": []},
        "forecast": [],
        "summary": {
            "expected_change_pct": 0.0,
            "trend": "震荡",
            "risk_level": "低",
            "confidence_level": "低",
            "text": f"{variety.name}·{region.name}暂无足够价格数据，无法生成预测。",
        },
        "explain": [],
        "feature_contributions": [],
        "created_at": created_at,
    }


def _build_forecast_payload(
    artifact: dict,
    model: ModelVersion,
    variety: Variety,
    region: Region,
    horizon: int,
) -> dict:
    series: pd.Series = artifact["series"]
    if series is None or len(series) < 30:
        return _empty_result_payload(variety, region, model, horizon)
    variety_id = int(variety.id)
    region_id = int(region.id)
    future_dates = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    predictions = _predict_base_models(
        artifact["fits"],
        future_dates,
        series,
        artifact.get("indicators"),
        artifact.get("last_indicators"),
        variety_id,
        region_id,
    )
    weights = artifact.get("weights") or {key: round(1.0 / 3, 4) for key in BASE_KEYS}
    predictions["ensemble"] = _weighted_predict(weights, predictions)
    key = str(model.key) if str(model.key) in predictions else "ensemble"
    points_array = np.clip(np.asarray(predictions[key], dtype=float), 0.01, None)

    last_actual = float(series.iloc[-1])
    recent_7 = float(np.mean(series.iloc[-7:])) if len(series) >= 7 else last_actual
    residual_std = float((artifact.get("residual_std") or {}).get(key) or 0.0)
    if residual_std <= 0:
        residual_std = max(last_actual * 0.02, 1e-6)
    mape = float((artifact.get("metrics") or {}).get(key, {}).get("mape") or model.mape or 0.0)
    direction_acc = float(
        (artifact.get("metrics") or {}).get(key, {}).get("direction_acc") or model.direction_acc or 0.0
    )

    points: list[dict] = []
    previous = last_actual
    for index, (target_date, point_value) in enumerate(zip(future_dates, points_array), start=1):
        point = round(max(float(point_value), 0.01), 2)
        widen = 1.96 * residual_std * math.sqrt(index / 7.0)
        lower = round(max(0.01, point - widen), 2)
        upper = round(point + widen, 2)
        change_pct = (point - previous) / previous * 100.0 if previous else 0.0
        if change_pct > 0.3:
            point_direction = "上涨"
        elif change_pct < -0.3:
            point_direction = "下跌"
        else:
            point_direction = "震荡"
        confidence = 0.95 - 0.01 * min(20.0, mape) - 0.004 * index
        points.append(
            {
                "target_date": target_date.strftime("%Y-%m-%d"),
                "point": point,
                "lower": lower,
                "upper": upper,
                "confidence": round(max(0.55, min(0.95, confidence)), 2),
                "direction": point_direction,
            }
        )
        previous = point

    # 未来 7 天均价 vs 最近 7 天实际均价，阈值 ±1%
    horizon_7 = min(7, len(points))
    future_mean_7 = float(np.mean([item["point"] for item in points[:horizon_7]]))
    direction_pct = (future_mean_7 / recent_7 - 1.0) * 100.0 if recent_7 else 0.0
    if direction_pct > 1.0:
        trend = "上涨"
    elif direction_pct < -1.0:
        trend = "下跌"
    else:
        trend = "震荡"

    last_point = points[-1]
    expected_change_pct = (last_point["point"] / last_actual - 1.0) * 100.0 if last_actual else 0.0
    abs_change = abs(expected_change_pct)
    if abs_change >= 8.0 or mape >= 8.0:
        risk_level = "高"
    elif abs_change >= 3.0 or mape >= 5.0:
        risk_level = "中"
    else:
        risk_level = "低"
    if mape <= 3.0 and direction_acc >= 60.0:
        confidence_level = "高"
    elif mape <= 6.0:
        confidence_level = "中"
    else:
        confidence_level = "低"

    history_len = min(90, len(series))
    history = {
        "dates": [d.strftime("%Y-%m-%d") for d in series.index[-history_len:]],
        "values": [round(float(v), 2) for v in series.iloc[-history_len:]],
    }

    explain_items = (artifact.get("feature_importance") or {}).get(key) or []
    explain = [
        {
            "factor": item.get("label", item.get("name", "")),
            "contribution": item.get("value", 0),
            "description": f"{item.get('label', item.get('name', ''))}对本次预测的相对贡献约 {item.get('value', 0)}%。",
        }
        for item in explain_items
    ]

    change_word = "上涨" if expected_change_pct > 0 else "下跌" if expected_change_pct < 0 else "基本持平"
    last_target = future_dates[-1].strftime("%Y-%m-%d")
    text = (
        f"{variety.name}·{region.name}未来{horizon}天预计{trend}，"
        f"到{last_target}价格约{last_point['point']:.2f}元/公斤，较当前价{change_word}"
        f"{abs(expected_change_pct):.2f}%；模型回测 MAPE {mape:.2f}%、方向准确率 {direction_acc:.1f}%（30日趋势方向），"
        f"风险等级{risk_level}。"
    )
    summary = {
        "expected_change_pct": round(expected_change_pct, 2),
        "trend": trend,
        "risk_level": risk_level,
        "confidence_level": confidence_level,
        "text": text,
        "direction_prob": round(direction_acc / 100.0, 4),
        "horizon_change_prob": round(direction_acc / 100.0, 4),
    }
    return {
        "forecast_id": None,
        "model": {
            "id": model.id,
            "key": key,
            "name": model.name,
            "version": model.version,
            "mape": round(mape, 2),
            "rmse": round(float(model.rmse or 0), 2),
            "direction_acc": round(direction_acc, 2),
            "direction_prob": round(direction_acc / 100.0, 4),
        },
        "history": history,
        "forecast": points,
        "summary": summary,
        "explain": explain,
        "feature_contributions": explain_items,
        "created_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _payload_from_row(db: Session, row: ForecastResult) -> dict | None:
    try:
        raw = json.loads(row.explain or "{}")
    except (ValueError, TypeError):
        raw = None
    if isinstance(raw, dict) and isinstance(raw.get("payload"), dict):
        payload = raw["payload"]
        payload["forecast_id"] = row.id
        return payload
    model = db.get(ModelVersion, row.model_id)
    if model is None:
        return None
    return {
        "forecast_id": row.id,
        "model": {
            "id": model.id,
            "key": model.key,
            "name": model.name,
            "version": model.version,
            "mape": round(float(model.mape or 0), 2),
            "direction_acc": round(float(model.direction_acc or 0), 2),
            "direction_prob": round(float(model.direction_acc or 0) / 100.0, 4),
        },
        "history": {"dates": [], "values": []},
        "forecast": [
            {
                "target_date": row.target_date.strftime("%Y-%m-%d"),
                "point": round(float(row.point), 2),
                "lower": round(float(row.lower), 2),
                "upper": round(float(row.upper), 2),
                "confidence": round(float(row.confidence or 0.8), 2),
                "direction": row.direction,
            }
        ],
        "summary": {
            "expected_change_pct": round(float(row.expected_change_pct or 0), 2),
            "trend": row.direction,
            "risk_level": "中",
            "confidence_level": "中",
            "text": row.summary_text,
        },
        "explain": [],
        "feature_contributions": [],
        "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S") if row.created_at else "",
    }


def _persist_forecast(
    db: Session,
    payload: dict,
    model: ModelVersion,
    variety_id: int,
    region_id: int,
    horizon: int,
    user: Any,
    commit: bool,
) -> ForecastResult:
    last_point = payload["forecast"][-1] if payload["forecast"] else None
    row = ForecastResult(
        model_id=model.id,
        variety_id=int(variety_id),
        region_id=int(region_id),
        granularity="day",
        horizon=int(horizon),
        forecast_date=date.today(),
        target_date=pd.Timestamp(last_point["target_date"]).date() if last_point else date.today(),
        point=float(last_point["point"]) if last_point else 0.0,
        lower=float(last_point["lower"]) if last_point else 0.0,
        upper=float(last_point["upper"]) if last_point else 0.0,
        confidence=float(last_point["confidence"]) if last_point else 0.8,
        direction=payload["summary"]["trend"],
        expected_change_pct=float(payload["summary"]["expected_change_pct"]),
        summary_text=payload["summary"]["text"],
        explain="{}",
        created_by=(getattr(user, "username", None) or "system") if user else "system",
        created_at=now(),
    )
    db.add(row)
    db.flush()
    payload["forecast_id"] = row.id
    row.explain = json.dumps(
        {"items": payload.get("explain", []), "payload": _jsonable(payload)},
        ensure_ascii=False,
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return row


def run_forecast(
    db: Session,
    user: Any,
    variety_id: int,
    region_id: int,
    horizon: int = DEFAULT_HORIZON,
    model_key: str | None = None,
    commit: bool = True,
) -> dict:
    """执行预测并持久化；同一品种+地区+模型+当日重复请求直接复用已有结果。"""
    variety, region = _ensure_pair(db, variety_id, region_id)
    horizon = _clamp_horizon(horizon)
    if model_key is not None and str(model_key) not in MODEL_KEYS:
        raise ApiError("E4001", f"不支持的模型标识：{model_key}", 400)

    model = _pick_model(db, variety_id, region_id, model_key)
    if model is None:
        models = train_model(db, variety_id, region_id, commit=commit)
        target_key = str(model_key) if model_key else "ensemble"
        model = next((m for m in models if m.key == target_key), models[-1])

    cached = db.execute(
        select(ForecastResult)
        .where(ForecastResult.model_id == model.id)
        .where(ForecastResult.variety_id == int(variety_id))
        .where(ForecastResult.region_id == int(region_id))
        .where(ForecastResult.horizon == int(horizon))
        .where(ForecastResult.forecast_date == date.today())
        .order_by(ForecastResult.id.desc())
    ).scalars().first()
    if cached is not None:
        payload = _payload_from_row(db, cached)
        if payload is not None:
            return payload

    try:
        artifact = _load_artifact(model)
    except ApiError:
        models = train_model(db, variety_id, region_id, commit=commit)
        model = next((m for m in models if m.key == model.key), models[-1])
        artifact = _load_artifact(model)

    payload = _build_forecast_payload(artifact, model, variety, region, horizon)
    row = _persist_forecast(db, payload, model, variety_id, region_id, horizon, user, commit)
    payload["forecast_id"] = row.id
    return payload


def forecast_result_detail(db: Session, result_id: int) -> dict:
    row = db.get(ForecastResult, int(result_id))
    if row is None:
        raise ApiError("E4040", "预测结果不存在", 404)
    payload = _payload_from_row(db, row)
    if payload is None:
        raise ApiError("E5000", "预测结果数据不完整，请重新执行预测", 500)
    return payload


def delete_forecast_result(db: Session, result_id: int, commit: bool = True) -> None:
    row = db.get(ForecastResult, int(result_id))
    if row is None:
        raise ApiError("E4040", "预测结果不存在", 404)
    db.delete(row)
    if commit:
        db.commit()


def forecast_results_list(
    db: Session,
    variety_id: int | None = None,
    region_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(200, int(limit or 20)))
    stmt = select(ForecastResult).order_by(ForecastResult.id.desc()).limit(limit)
    if variety_id:
        stmt = stmt.where(ForecastResult.variety_id == int(variety_id))
    if region_id:
        stmt = stmt.where(ForecastResult.region_id == int(region_id))
    rows = db.execute(stmt).scalars().all()
    varieties, regions = _name_maps(db)
    model_map = {
        int(m.id): m
        for m in db.execute(
            select(ModelVersion).where(ModelVersion.id.in_([r.model_id for r in rows] or [0]))
        ).scalars().all()
    }
    result = []
    for row in rows:
        model = model_map.get(int(row.model_id))
        result.append(
            {
                "id": row.id,
                "variety_id": row.variety_id,
                "variety": varieties.get(int(row.variety_id), ""),
                "region_id": row.region_id,
                "region": regions.get(int(row.region_id), ""),
                "horizon": row.horizon,
                "model": model.name if model else "",
                "model_key": model.key if model else "",
                "mape": round(float(model.mape or 0), 2) if model else 0,
                "expected_change_pct": round(float(row.expected_change_pct or 0), 2),
                "direction": row.direction,
                "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S") if row.created_at else "",
            }
        )
    return result


def forecast_performance(db: Session) -> dict:
    """预测性能汇总：active 模型的平均 MAPE / 方向准确率及按品种、按时间分布。"""
    models = db.execute(
        select(ModelVersion).where(ModelVersion.is_active.is_(True)).order_by(ModelVersion.variety_id)
    ).scalars().all()
    varieties, _regions = _name_maps(db)
    if not models:
        return {"avg_mape": 0.0, "avg_direction_acc": 0.0, "series": [], "by_variety": []}
    avg_mape = float(np.mean([float(m.mape or 0) for m in models]))
    avg_dir = float(np.mean([float(m.direction_acc or 0) for m in models]))

    by_date: dict[str, list[tuple[float, float]]] = {}
    for model in models:
        key = model.trained_at.strftime("%Y-%m-%d") if model.trained_at else ""
        by_date.setdefault(key, []).append((float(model.mape or 0), float(model.direction_acc or 0)))
    series = [
        {
            "date": day,
            "mape": round(float(np.mean([item[0] for item in values])), 2),
            "direction_acc": round(float(np.mean([item[1] for item in values])), 2),
        }
        for day, values in sorted(by_date.items())[-30:]
    ]

    grouped: dict[str, list[tuple[float, float]]] = {}
    for model in models:
        grouped.setdefault(varieties.get(int(model.variety_id), ""), []).append(
            (float(model.mape or 0), float(model.direction_acc or 0))
        )
    by_variety = [
        {
            "variety": name,
            "mape": round(float(np.mean([item[0] for item in values])), 2),
            "direction_acc": round(float(np.mean([item[1] for item in values])), 2),
        }
        for name, values in grouped.items()
    ]
    return {
        "avg_mape": round(avg_mape, 2),
        "avg_direction_acc": round(avg_dir, 2),
        "direction_acc_note": "方向准确率=30日累计趋势方向命中率（7日移动平均去噪，滚动重训口径；7日/单日口径见 direction_acc_7d / direction_acc_1d）",
        "series": series,
        "by_variety": by_variety,
    }


# ============================ 回测 ============================

def _backtest_points(
    artifact: dict,
    model_key: str,
    variety_id: int,
    region_id: int,
    days: int,
) -> list[dict]:
    series: pd.Series = artifact["series"]
    n = len(series)
    days = max(7, min(int(days), n - 40))
    if days < 7:
        raise ApiError("E4001", "价格数据不足，无法回测", 400)
    indicators = artifact.get("indicators")
    last_indicators = artifact.get("last_indicators")
    weights = artifact.get("weights") or {key: round(1.0 / 3, 4) for key in BASE_KEYS}
    block = 14
    start = n - days
    records: list[dict] = []
    position = start
    while position < n:
        current_block = min(block, n - position)
        train_series = series.iloc[:position]
        matrix = feat.matrix_from_series(train_series, indicators, variety_id, region_id, last_indicators)
        fits = _fit_base_models(train_series, matrix, variety_id, region_id)
        future_dates = series.index[position : position + current_block]
        predictions = _predict_base_models(
            fits, future_dates, train_series, indicators, last_indicators, variety_id, region_id
        )
        predictions["ensemble"] = _weighted_predict(weights, predictions)
        chosen = predictions.get(model_key)
        if chosen is None:  # 指定模型不可用时回退组合预测（不可用 `or`，numpy 数组布尔判定有歧义）
            chosen = predictions["ensemble"]
        for offset, target_date in enumerate(future_dates):
            records.append(
                {
                    "date": target_date.strftime("%Y-%m-%d"),
                    "actual": round(float(series.iloc[position + offset]), 2),
                    "predicted": round(float(chosen[offset]), 2),
                }
            )
        position += current_block

    actual = [item["actual"] for item in records]
    predicted = [item["predicted"] for item in records]
    std = _residual_std(actual, predicted)
    for item in records:
        item["lower"] = round(max(0.01, item["predicted"] - 1.96 * std), 2)
        item["upper"] = round(item["predicted"] + 1.96 * std, 2)
    return records


def backtest_model(db: Session, model: ModelVersion, days: int = 60, commit: bool = True) -> dict:
    """滚动回测：每 14 天重训一次，逐日输出实际值/预测值/区间，并写 BacktestRecord。"""
    if model is None:
        raise ApiError("E4040", "模型不存在", 404)
    try:
        days = int(days if days is not None else 60)
    except (TypeError, ValueError):
        raise ApiError("E4001", "回测窗口必须为整数", 400)
    if days < 7 or days > 180:
        raise ApiError("E4001", "回测窗口需在 7~180 天之间", 400)

    artifact = _load_artifact(model)
    records = _backtest_points(artifact, str(model.key), int(model.variety_id), int(model.region_id), days)
    metrics = _metrics([r["actual"] for r in records], [r["predicted"] for r in records])

    existing = db.execute(
        select(BacktestRecord).where(BacktestRecord.model_id == model.id)
    ).scalars().all()
    for row in existing:
        db.delete(row)
    for item in records:
        db.add(
            BacktestRecord(
                model_id=model.id,
                date=pd.Timestamp(item["date"]).date(),
                actual=float(item["actual"]),
                predicted=float(item["predicted"]),
                lower=float(item["lower"]),
                upper=float(item["upper"]),
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()

    params: dict = {}
    try:
        params = json.loads(model.params or "{}")
    except (ValueError, TypeError):
        params = {}
    importance = params.get("feature_importance") or []
    feature_importance = [
        {"factor": item.get("label", item.get("name", "")), "value": item.get("value", 0)}
        for item in importance
    ]
    return {
        "window": int(days),
        "points": records,
        "metrics": metrics,
        "feature_importance": feature_importance,
    }


def get_backtest(db: Session, model: ModelVersion, window: int = 60) -> dict:
    """优先复用已存回测记录，不足时重新滚动回测。"""
    if model is None:
        raise ApiError("E4040", "模型不存在", 404)
    try:
        window = int(window if window is not None else 60)
    except (TypeError, ValueError):
        raise ApiError("E4001", "回测窗口必须为整数", 400)
    window = max(7, min(180, window))
    rows = db.execute(
        select(BacktestRecord)
        .where(BacktestRecord.model_id == model.id)
        .order_by(BacktestRecord.date)
    ).scalars().all()
    if len(rows) < window:
        return backtest_model(db, model, days=window, commit=True)
    rows = rows[-window:]
    points = [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "actual": round(float(row.actual), 2),
            "predicted": round(float(row.predicted), 2),
            "lower": round(float(row.lower), 2),
            "upper": round(float(row.upper), 2),
        }
        for row in rows
    ]
    metrics = _metrics([p["actual"] for p in points], [p["predicted"] for p in points])
    try:
        params = json.loads(model.params or "{}")
    except (ValueError, TypeError):
        params = {}
    importance = params.get("feature_importance") or []
    feature_importance = [
        {"factor": item.get("label", item.get("name", "")), "value": item.get("value", 0)}
        for item in importance
    ]
    return {
        "window": window,
        "points": points,
        "metrics": metrics,
        "feature_importance": feature_importance,
    }


# ============================ 批量预测 ============================

def _parse_id_list(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [item for item in raw.replace("，", ",").split(",") if item.strip()]
    try:
        return [int(item) for item in raw]
    except (TypeError, ValueError):
        raise ApiError("E4001", "品种/地区参数格式不正确", 400)


def run_forecast_batch(
    db: Session,
    user: Any,
    variety_ids: Any = None,
    region_ids: Any = None,
    horizon: int = DEFAULT_HORIZON,
    model_key: str | None = None,
    commit: bool = True,
) -> dict:
    """同步批量预测（≤200 条），写 ForecastBatch/ForecastBatchItem。"""
    horizon = _clamp_horizon(horizon)
    vids = _parse_id_list(variety_ids)
    rids = _parse_id_list(region_ids)
    if not vids:
        vids = [int(v) for v in db.execute(select(Variety.id).where(Variety.enabled.is_(True)).order_by(Variety.id)).scalars()]
    if not rids:
        rids = [int(r) for r in db.execute(select(Region.id).where(Region.enabled.is_(True)).order_by(Region.id)).scalars()]
    if not vids or not rids:
        raise ApiError("E4001", "请先选择品种与地区", 400)
    pairs = [(v, r) for v in vids for r in rids]
    if len(pairs) > MAX_BATCH:
        raise ApiError("E4001", f"单次批量预测不超过 {MAX_BATCH} 条", 400)

    created_by = (getattr(user, "username", None) or "system") if user else "system"
    batch = ForecastBatch(
        variety_ids=",".join(str(v) for v in vids),
        region_ids=",".join(str(r) for r in rids),
        horizon=horizon,
        total=len(pairs),
        done=0,
        status="处理中",
        created_by=created_by,
        created_at=now(),
    )
    db.add(batch)
    db.flush()

    varieties, regions = _name_maps(db)
    errors: list[dict] = []
    done = 0
    for variety_id, region_id in pairs:
        try:
            payload = run_forecast(
                db, user, variety_id, region_id, horizon, model_key, commit=False
            )
            last = payload["forecast"][-1] if payload["forecast"] else None
            db.add(
                ForecastBatchItem(
                    batch_id=batch.id,
                    variety_id=int(variety_id),
                    region_id=int(region_id),
                    point=float(last["point"]) if last else 0.0,
                    lower=float(last["lower"]) if last else 0.0,
                    upper=float(last["upper"]) if last else 0.0,
                    direction=payload["summary"]["trend"],
                    mape=float(payload["model"].get("mape") or 0),
                )
            )
            done += 1
        except ApiError as exc:
            errors.append(
                {
                    "variety_id": variety_id,
                    "region_id": region_id,
                    "variety": varieties.get(int(variety_id), ""),
                    "region": regions.get(int(region_id), ""),
                    "message": exc.message,
                }
            )
        except Exception as exc:  # pragma: no cover - 单条失败不拖垮批次
            errors.append(
                {
                    "variety_id": variety_id,
                    "region_id": region_id,
                    "variety": varieties.get(int(variety_id), ""),
                    "region": regions.get(int(region_id), ""),
                    "message": f"预测失败：{exc}",
                }
            )
    batch.done = done
    if done == batch.total:
        batch.status = "已完成"
    elif done > 0:
        batch.status = "部分完成"
    else:
        batch.status = "失败"
    db.add(batch)
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "batch_id": batch.id,
        "total": batch.total,
        "done": done,
        "status": batch.status,
        "created_at": batch.created_at.strftime("%Y-%m-%dT%H:%M:%S") if batch.created_at else "",
        "errors": errors,
    }


def get_batch_detail(db: Session, batch_id: int) -> dict:
    batch = db.get(ForecastBatch, int(batch_id))
    if batch is None:
        raise ApiError("E4040", "预测批次不存在", 404)
    varieties, regions = _name_maps(db)
    items = db.execute(
        select(ForecastBatchItem)
        .where(ForecastBatchItem.batch_id == batch.id)
        .order_by(ForecastBatchItem.id)
    ).scalars().all()
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "done": batch.done,
        "total": batch.total,
        "horizon": batch.horizon,
        "created_by": batch.created_by,
        "created_at": batch.created_at.strftime("%Y-%m-%dT%H:%M:%S") if batch.created_at else "",
        "items": [
            {
                "variety_id": item.variety_id,
                "variety": varieties.get(int(item.variety_id), ""),
                "region_id": item.region_id,
                "region": regions.get(int(item.region_id), ""),
                "point": round(float(item.point or 0), 2),
                "lower": round(float(item.lower or 0), 2),
                "upper": round(float(item.upper or 0), 2),
                "direction": item.direction,
                "mape": round(float(item.mape or 0), 2),
            }
            for item in items
        ],
    }


def batch_export_rows(db: Session, batch_id: int) -> list[list[Any]]:
    detail = get_batch_detail(db, batch_id)
    rows: list[list[Any]] = [["品种", "地区", "预测价格", "区间下限", "区间上限", "方向", "MAPE(%)"]]
    for item in detail["items"]:
        rows.append(
            [
                item["variety"],
                item["region"],
                item["point"],
                item["lower"],
                item["upper"],
                item["direction"],
                item["mape"],
            ]
        )
    return rows


def batch_list(db: Session, limit: int = 20) -> list[dict]:
    limit = max(1, min(200, int(limit or 20)))
    batches = db.execute(
        select(ForecastBatch).order_by(ForecastBatch.id.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "batch_id": batch.id,
            "horizon": batch.horizon,
            "total": batch.total,
            "done": batch.done,
            "status": batch.status,
            "created_by": batch.created_by,
            "created_at": batch.created_at.strftime("%Y-%m-%dT%H:%M:%S") if batch.created_at else "",
        }
        for batch in batches
    ]


# ============================ 模型管理查询 ============================

def serialize_model(
    model: ModelVersion,
    variety_name: str = "",
    region_name: str = "",
) -> dict:
    return {
        "id": model.id,
        "key": model.key,
        "name": model.name,
        "algorithm": model.algorithm,
        "variety_id": model.variety_id,
        "variety": variety_name,
        "region_id": model.region_id,
        "region": region_name,
        "granularity": model.granularity,
        "status": model.status,
        "is_active": bool(model.is_active),
        "version": model.version,
        "mape": round(float(model.mape or 0), 2),
        "rmse": round(float(model.rmse or 0), 2),
        "direction_acc": round(float(model.direction_acc or 0), 2),
        "rows": int(model.rows or 0),
        "trained_at": model.trained_at.strftime("%Y-%m-%dT%H:%M:%S") if model.trained_at else "",
    }


def list_models(
    db: Session,
    variety_id: int | None = None,
    region_id: int | None = None,
    key: str | None = None,
) -> list[dict]:
    stmt = select(ModelVersion).order_by(
        ModelVersion.variety_id, ModelVersion.region_id, ModelVersion.key, ModelVersion.id.desc()
    )
    if variety_id:
        stmt = stmt.where(ModelVersion.variety_id == int(variety_id))
    if region_id:
        stmt = stmt.where(ModelVersion.region_id == int(region_id))
    if key:
        stmt = stmt.where(ModelVersion.key == str(key))
    rows = db.execute(stmt).scalars().all()
    varieties, regions = _name_maps(db)
    return [
        serialize_model(
            model,
            varieties.get(int(model.variety_id), ""),
            regions.get(int(model.region_id), ""),
        )
        for model in rows
    ]


def get_model(db: Session, model_id: int) -> ModelVersion:
    model = db.get(ModelVersion, int(model_id))
    if model is None:
        raise ApiError("E4040", "模型不存在", 404)
    return model


def compare_models(db: Session, variety_id: int, region_id: int) -> list[dict]:
    """同一品种×地区下每个算法的最新版本指标对比。"""
    _ensure_pair(db, variety_id, region_id)
    varieties, regions = _name_maps(db)
    result: list[dict] = []
    for key in MODEL_KEYS:
        model = db.execute(
            select(ModelVersion)
            .where(ModelVersion.variety_id == int(variety_id))
            .where(ModelVersion.region_id == int(region_id))
            .where(ModelVersion.key == key)
            .order_by(ModelVersion.trained_at.desc(), ModelVersion.id.desc())
        ).scalars().first()
        if model is None:
            continue
        payload = serialize_model(
            model, varieties.get(int(model.variety_id), ""), regions.get(int(model.region_id), "")
        )
        try:
            params = json.loads(model.params or "{}")
        except (ValueError, TypeError):
            params = {}
        payload["weights"] = params.get("weights")
        payload["feature_importance"] = params.get("feature_importance") or []
        result.append(payload)
    return result


def train_models_for(
    db: Session,
    variety_id: int | None = None,
    region_id: int | None = None,
    model_key: str | None = None,
    commit: bool = True,
) -> list[ModelVersion]:
    """路由层训练入口：指定组合训练；缺省为全部启用组合补齐 active 模型。"""
    if model_key is not None and str(model_key) not in MODEL_KEYS:
        raise ApiError("E4001", f"不支持的模型标识：{model_key}", 400)
    if variety_id and region_id:
        _ensure_pair(db, variety_id, region_id)
        return train_model(db, int(variety_id), int(region_id), commit=commit)
    return ensure_active_models(
        db,
        variety_ids=[int(variety_id)] if variety_id else None,
        region_ids=[int(region_id)] if region_id else None,
        commit=commit,
    )
