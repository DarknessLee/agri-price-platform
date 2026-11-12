"""Redis 缓存层：单例连接、JSON 读写、按前缀失效与可用性探测。

设计原则：
- Redis 只是加速层：任何连接 / 命令异常都返回未命中或 False，由调用方回源数据库，
  绝不让业务接口因缓存故障返回 500；
- 异常只告警一次（进程内去重），避免 Redis 掉线时日志刷屏；
- 连接超时 1s、命令超时 0.5s，保证故障时接口延迟可控；
- 统一 key 形态 ``<CACHE_PREFIX>:<domain>:<hash>``，失效用 SCAN 按域清理（不用 KEYS）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

import redis

from .config import CACHE_ENABLED, CACHE_PREFIX, REDIS_URL

logger = logging.getLogger("agri.cache")

CONNECT_TIMEOUT = 1.0
SOCKET_TIMEOUT = 0.5
# 故障后快速降级的冷却时长（秒）：冷却期内跳过 Redis 调用，避免每次请求都等连接超时
RECOVER_INTERVAL = 15.0

_client: redis.Redis | None = None
_client_lock = threading.Lock()
_warned = False
_status: bool | None = None
_status_lock = threading.Lock()
_cooldown_until = 0.0


# ---------------------------------------------------------------- 客户端

def _unavailable() -> bool:
    """冷却期内视为不可用，直接降级（避免故障时反复等待超时）。"""
    return _cooldown_until > 0 and time.monotonic() < _cooldown_until

def get_client() -> redis.Redis | None:
    """惰性创建并复用 Redis 客户端；缓存关闭时返回 None。"""
    global _client
    if not CACHE_ENABLED:
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = redis.Redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=CONNECT_TIMEOUT,
                socket_timeout=SOCKET_TIMEOUT,
                health_check_interval=30,
                retry_on_timeout=False,
            )
    return _client


def note_cache_status(ok: bool, exc: BaseException | None = None) -> None:
    """记录缓存可用状态；失败仅首次告警，供健康检查与降级调用。"""
    global _status, _warned, _cooldown_until
    with _status_lock:
        _status = bool(ok)
        if ok:
            _cooldown_until = 0.0
            return
        if _warned:
            return
        _warned = True
    detail = f"：{exc}" if exc is not None else ""
    message = f"Redis 缓存不可用，已降级为直连数据库{detail}"
    logger.warning(message)
    print(f"[cache] {message}")


def _degrade(exc: BaseException) -> None:
    """命令失败时的统一降级处理：记录状态并进入冷却期。"""
    global _cooldown_until
    note_cache_status(False, exc)
    _cooldown_until = time.monotonic() + RECOVER_INTERVAL


def cache_available() -> bool:
    """探测 Redis 是否可用（PING）；关闭缓存或异常均返回 False。"""
    if not CACHE_ENABLED:
        note_cache_status(False)
        return False
    client = get_client()
    if client is None:
        note_cache_status(False)
        return False
    try:
        client.ping()
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return False
    note_cache_status(True)
    return True


# ---------------------------------------------------------------- 键工具

def make_key(domain: str, *parts: Any) -> str:
    """生成 ``<prefix>:<domain>:<hash>`` 缓存键；参数压成短哈希，避免超长与特殊字符。"""
    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16] if payload else "all"
    return f"{CACHE_PREFIX}:{domain}:{digest}"


def domain_prefix(domain: str) -> str:
    """某个缓存域的键前缀（不含通配符）。"""
    return f"{CACHE_PREFIX}:{domain}:"


def blacklist_key(token_digest: str) -> str:
    """JWT 黑名单键：``agri:jwt:blacklist:<sha256>``。"""
    return f"{CACHE_PREFIX}:jwt:blacklist:{token_digest}"


# ---------------------------------------------------------------- 读写

def get(key: str) -> Any | None:
    """读取并反序列化 JSON；未命中或 Redis 异常返回 None。"""
    client = get_client()
    if client is None or _unavailable():
        return None
    try:
        raw = client.get(key)
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return None
    if raw is None:
        note_cache_status(True)
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("缓存值不是合法 JSON，忽略并回源：%s", key)
        return None


def set(key: str, value: Any, ttl: int | None = None) -> bool:  # noqa: A001 - 与任务约定命名一致
    """JSON 序列化后写入；成功返回 True，Redis 异常返回 False。"""
    client = get_client()
    if client is None or _unavailable():
        return False
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("缓存值无法序列化，跳过写入 %s：%s", key, exc)
        return False
    try:
        if ttl and int(ttl) > 0:
            client.set(key, raw, ex=int(ttl))
        else:
            client.set(key, raw)
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return False
    note_cache_status(True)
    return True


def get_raw(key: str) -> str | None:
    """读取原始字符串（令牌黑名单等非 JSON 场景）。"""
    client = get_client()
    if client is None or _unavailable():
        return None
    try:
        return client.get(key)
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return None


def set_raw(key: str, value: str, ttl: int | None = None) -> bool:
    """写入原始字符串（不序列化）。"""
    client = get_client()
    if client is None or _unavailable():
        return False
    try:
        if ttl and int(ttl) > 0:
            client.set(key, value, ex=int(ttl))
        else:
            client.set(key, value)
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return False
    note_cache_status(True)
    return True


def exists(key: str) -> bool:
    """判断键是否存在；Redis 异常返回 False（降级放行）。"""
    client = get_client()
    if client is None or _unavailable():
        return False
    try:
        return bool(client.exists(key))
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return False


def delete(key: str) -> bool:
    """删除单个键。"""
    client = get_client()
    if client is None or _unavailable():
        return False
    try:
        client.delete(key)
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
        return False
    return True


def delete_prefix(prefix: str) -> int:
    """用 SCAN 增量遍历并删除某前缀下的全部键，返回删除数量。"""
    client = get_client()
    if client is None or _unavailable():
        return 0
    removed = 0
    batch: list[str] = []
    try:
        for key in client.scan_iter(match=f"{prefix}*", count=500):
            batch.append(key)
            if len(batch) >= 500:
                removed += int(client.delete(*batch))
                batch.clear()
        if batch:
            removed += int(client.delete(*batch))
    except (redis.RedisError, OSError) as exc:
        _degrade(exc)
    return removed


def invalidate(*domains: str) -> int:
    """按缓存域清理，例如 ``invalidate("dashboard", "prices", "meta")``。"""
    return sum(delete_prefix(domain_prefix(domain)) for domain in domains)
