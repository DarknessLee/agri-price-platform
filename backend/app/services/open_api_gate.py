"""开放 API 治理：鉴权（Bearer / X-Api-Key）、限流与调用流水（契约 M2 §6）。

- 鉴权：``Authorization: Bearer <JWT>`` 或 ``X-Api-Key: <client_key>``；无效/停用 → 401 E4010。
- 限流：按调用方 ``open_api_client.rate_limit``（次/分钟）计数；优先 Redis INCR+EXPIRE，
  Redis 不可用时降级为进程内内存计数；超限 → 429 E4290。
- 流水：每次已鉴权调用写 ``open_api_call``（path/method/status/elapsed_ms），累计调用方
  ``call_count`` / ``last_call_at``，并在写入时顺带清理超过保留天数的历史流水。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

import redis
from fastapi import Depends, Header, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import cache
from ..config import OPEN_API_CALL_RETENTION_DAYS, OPEN_API_RATE_LIMIT
from ..database import get_db, now
from ..models import OpenApiCall, OpenApiClient, User
from ..security import ApiError, get_current_user

# 限流窗口：1 分钟
RATE_WINDOW_SECONDS = 60
# Redis 故障后的冷却时长：冷却期内跳过 Redis，直接走内存降级
REDIS_RECOVER_INTERVAL = 15.0

_memory_lock = threading.Lock()
_memory_counters: dict[str, tuple[float, int]] = {}
_redis_down_until = 0.0


@dataclass
class OpenApiPrincipal:
    """开放 API 调用主体：JWT 用户或 API 调用方。"""

    auth_type: str  # "jwt" | "api-key"
    user: User | None = None
    client: OpenApiClient | None = None


# ---------------------------------------------------------------- 限流

def _rate_key(client_id: int) -> str:
    window = int(time.time() // RATE_WINDOW_SECONDS)
    return f"agri:openapi:rate:{int(client_id)}:{window}"


def _redis_rate_hit(client_id: int) -> int | None:
    """Redis 原子计数；不可用（或冷却中）返回 None 交由内存降级。"""
    global _redis_down_until
    if _redis_down_until > 0 and time.monotonic() < _redis_down_until:
        return None
    client = cache.get_client()
    if client is None:
        return None
    key = _rate_key(client_id)
    try:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, RATE_WINDOW_SECONDS + 5)
        return count
    except (redis.RedisError, OSError):
        _redis_down_until = time.monotonic() + REDIS_RECOVER_INTERVAL
        return None


def _memory_rate_hit(client_id: int) -> int:
    """Redis 不可用时的进程内计数（单实例部署足够，多实例属降级容忍）。"""
    window = int(time.time() // RATE_WINDOW_SECONDS)
    key = f"{int(client_id)}:{window}"
    with _memory_lock:
        stale = [item for item in _memory_counters if item.rsplit(":", 1)[-1] != str(window)]
        for item in stale:
            _memory_counters.pop(item, None)
        count = (_memory_counters.get(key, (0.0, 0))[1]) + 1
        _memory_counters[key] = (float(window), count)
    return count


def check_rate_limit(client: OpenApiClient) -> None:
    """按调用方限流配置计数，超限抛 429 E4290。"""
    limit = int(client.rate_limit or OPEN_API_RATE_LIMIT)
    if limit <= 0:
        limit = OPEN_API_RATE_LIMIT
    count = _redis_rate_hit(int(client.id))
    if count is None:
        count = _memory_rate_hit(int(client.id))
    if count > limit:
        raise ApiError("E4290", "调用频率超出限制，请稍后重试", 429)


# ---------------------------------------------------------------- 鉴权

def _client_by_key(db: Session, client_key: str) -> OpenApiClient | None:
    return db.execute(
        select(OpenApiClient).where(OpenApiClient.client_key == str(client_key))
    ).scalars().first()


def resolve_principal(
    db: Session,
    authorization: str | None,
    x_api_key: str | None,
) -> OpenApiPrincipal:
    """解析调用主体：优先 X-Api-Key，其次 Bearer JWT。"""
    if x_api_key and x_api_key.strip():
        client = _client_by_key(db, x_api_key.strip())
        if client is None or not bool(client.enabled):
            raise ApiError("E4010", "开放 API 密钥无效或已停用", 401)
        check_rate_limit(client)
        return OpenApiPrincipal(auth_type="api-key", client=client)
    user = get_current_user(authorization, db)
    return OpenApiPrincipal(auth_type="jwt", user=user)


# ---------------------------------------------------------------- 流水

def record_call(
    db: Session,
    request: Request,
    principal: OpenApiPrincipal,
    status: int,
    started: float,
) -> None:
    """写调用流水并累计调用方统计；失败不影响主请求。"""
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    try:
        if status >= 400:
            db.rollback()
        call = OpenApiCall(
            client_id=int(principal.client.id) if principal.client is not None else 0,
            path=str(request.url.path)[:128],
            method=str(request.method)[:8],
            status=int(status),
            elapsed_ms=elapsed_ms,
            created_at=now(),
        )
        db.add(call)
        if principal.client is not None:
            client = db.get(OpenApiClient, int(principal.client.id))
            if client is not None:
                client.call_count = int(client.call_count or 0) + 1
                client.last_call_at = now()
                db.add(client)
        cutoff = now() - timedelta(days=OPEN_API_CALL_RETENTION_DAYS)
        db.execute(delete(OpenApiCall).where(OpenApiCall.created_at < cutoff))
        db.commit()
    except Exception:  # 流水写入失败不影响业务返回
        try:
            db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------- 依赖

def open_api_guard(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    """FastAPI 依赖：完成鉴权 + 限流，并在请求结束时记录调用流水。"""
    principal = resolve_principal(db, authorization, x_api_key)
    started = time.perf_counter()
    status = 200
    try:
        yield principal
    except ApiError as exc:
        status = int(exc.http_status)
        raise
    except Exception:
        status = 500
        raise
    finally:
        record_call(db, request, principal, status, started)
