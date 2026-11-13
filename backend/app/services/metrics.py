"""进程内指标采集：按分钟聚合 QPS、耗时分布、错误率与缓存命中，供监控页展示。

为什么不用 Prometheus：单机验收环境引入 Prometheus + Grafana 需要额外两个容器与配置，
而本平台只需要最近一小时的运行画像。分钟桶 + 固定直方图边界即可给出 p50/p95/p99，
内存占用可控（默认保留 120 个桶），重启后自然清零，符合"零外部依赖也能跑"的原则。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta

from ..config import METRICS_ENABLED, METRICS_WINDOW_MINUTES

# 耗时直方图边界（毫秒），最后一个区间为 >= 5000ms
_BUCKETS = [5, 10, 20, 30, 50, 80, 120, 200, 300, 500, 800, 1200, 2000, 3000, 5000]
_MAX_MINUTES = max(METRICS_WINDOW_MINUTES, 30) + 60

_lock = threading.Lock()
_minutes: dict[str, dict] = {}


def _minute_key(when: float | None = None) -> str:
    moment = datetime.fromtimestamp(when if when is not None else time.time())
    return moment.strftime("%Y-%m-%d %H:%M")


def _empty_bucket() -> dict:
    return {
        "count": 0,
        "errors": 0,
        "sum_ms": 0.0,
        "buckets": [0] * len(_BUCKETS),
        "slow": deque(maxlen=20),
        "cache": {"HIT": 0, "MISS": 0, "BYPASS": 0},
        "paths": {},
    }


def _prune() -> None:
    if len(_minutes) <= _MAX_MINUTES:
        return
    for key in sorted(_minutes)[: len(_minutes) - _MAX_MINUTES]:
        _minutes.pop(key, None)


def record_request(
    method: str, path: str, status: int, elapsed_ms: float, cache: str | None = None
) -> None:
    """记录一次请求；禁用指标时直接返回。"""
    if not METRICS_ENABLED:
        return
    path = (path or "/").split("?")[0]
    # 数字 ID 归一化，避免路径基数膨胀
    parts = []
    for segment in path.split("/"):
        parts.append("{id}" if segment.isdigit() else segment)
    normalized = "/".join(parts) or "/"
    key = _minute_key()
    with _lock:
        bucket = _minutes.get(key)
        if bucket is None:
            bucket = _empty_bucket()
            _minutes[key] = bucket
            _prune()
        bucket["count"] += 1
        bucket["sum_ms"] += float(elapsed_ms)
        if int(status or 0) >= 400:
            bucket["errors"] += 1
        index = len(_BUCKETS)
        for position, edge in enumerate(_BUCKETS):
            if elapsed_ms <= edge:
                index = position
                break
        bucket["buckets"][index] += 1
        if elapsed_ms >= 500:
            bucket["slow"].append(
                {
                    "method": method,
                    "path": normalized,
                    "status": int(status or 0),
                    "elapsed_ms": round(float(elapsed_ms), 1),
                    "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
        cache_key = (cache or "BYPASS").upper()
        if cache_key not in bucket["cache"]:
            cache_key = "BYPASS"
        bucket["cache"][cache_key] += 1
        path_stat = bucket["paths"].setdefault(normalized, {"count": 0, "sum_ms": 0.0, "errors": 0})
        path_stat["count"] += 1
        path_stat["sum_ms"] += float(elapsed_ms)
        if int(status or 0) >= 400:
            path_stat["errors"] += 1


def _percentile(counts: list[int], total: int, ratio: float) -> float:
    if total <= 0:
        return 0.0
    target = total * ratio
    cumulative = 0
    for index, count in enumerate(counts):
        cumulative += count
        if cumulative >= target:
            if index >= len(_BUCKETS):
                return float(_BUCKETS[-1])
            # 区间内按线性插值，避免只给出粗糙边界
            lower = 0 if index == 0 else _BUCKETS[index - 1]
            upper = _BUCKETS[index]
            return round(lower + (upper - lower) * 0.5, 1)
    return float(_BUCKETS[-1])


def summary(minutes: int = 60) -> dict:
    """最近 N 分钟的汇总指标。"""
    minutes = max(1, min(int(minutes or 60), _MAX_MINUTES))
    now = datetime.now()
    keys = [(now - timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M") for offset in range(minutes)]
    with _lock:
        selected = [_minutes[key] for key in keys if key in _minutes]
        totals = {
            "count": sum(bucket["count"] for bucket in selected),
            "errors": sum(bucket["errors"] for bucket in selected),
            "sum_ms": sum(bucket["sum_ms"] for bucket in selected),
            "buckets": [sum(bucket["buckets"][i] for bucket in selected) for i in range(len(_BUCKETS))],
            "cache": {
                name: sum(bucket["cache"].get(name, 0) for bucket in selected)
                for name in ("HIT", "MISS", "BYPASS")
            },
            "paths": {},
        }
        slow: list[dict] = []
        for bucket in selected:
            slow.extend(list(bucket["slow"]))
        for bucket in selected:
            for path, stat in bucket["paths"].items():
                merged = totals["paths"].setdefault(path, {"count": 0, "sum_ms": 0.0, "errors": 0})
                merged["count"] += stat["count"]
                merged["sum_ms"] += stat["sum_ms"]
                merged["errors"] += stat["errors"]
    count = totals["count"]
    errors = totals["errors"]
    cache_total = sum(totals["cache"].values())
    slow.sort(key=lambda item: item["elapsed_ms"], reverse=True)
    slow_top = [
        {
            "path": path,
            "count": stat["count"],
            "avg_ms": round(stat["sum_ms"] / stat["count"], 1) if stat["count"] else 0.0,
            "error_rate": round(stat["errors"] / stat["count"] * 100, 2) if stat["count"] else 0.0,
        }
        for path, stat in totals["paths"].items()
    ]
    slow_top.sort(key=lambda item: item["avg_ms"], reverse=True)
    return {
        "window_minutes": minutes,
        "qps": round(count / (minutes * 60), 3),
        "avg_ms": round(totals["sum_ms"] / count, 1) if count else 0.0,
        "p50_ms": _percentile(totals["buckets"], count, 0.50),
        "p95_ms": _percentile(totals["buckets"], count, 0.95),
        "p99_ms": _percentile(totals["buckets"], count, 0.99),
        "error_rate": round(errors / count * 100, 2) if count else 0.0,
        "total": count,
        "errors": errors,
        "cache": {
            **totals["cache"],
            "hit_rate": round(totals["cache"]["HIT"] / cache_total * 100, 2) if cache_total else 0.0,
        },
        "slow_top": slow_top[:8],
        "slowest": slow[:8],
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def timeseries(minutes: int = 60) -> list[dict]:
    """逐分钟时序，缺失分钟补 0，便于前端直接画折线。"""
    minutes = max(1, min(int(minutes or 60), _MAX_MINUTES))
    now = datetime.now().replace(second=0, microsecond=0)
    series: list[dict] = []
    with _lock:
        for offset in range(minutes - 1, -1, -1):
            moment = now - timedelta(minutes=offset)
            key = moment.strftime("%Y-%m-%d %H:%M")
            bucket = _minutes.get(key)
            if bucket is None:
                series.append({"minute": key, "qps": 0.0, "avg_ms": 0.0, "error_rate": 0.0, "total": 0})
                continue
            count = bucket["count"]
            series.append(
                {
                    "minute": key,
                    "qps": round(count / 60, 3),
                    "avg_ms": round(bucket["sum_ms"] / count, 1) if count else 0.0,
                    "error_rate": round(bucket["errors"] / count * 100, 2) if count else 0.0,
                    "total": count,
                }
            )
    return series


def reset() -> None:
    """清空采集（测试与门禁使用）。"""
    with _lock:
        _minutes.clear()
