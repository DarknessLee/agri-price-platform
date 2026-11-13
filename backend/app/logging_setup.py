"""结构化日志：JSON Lines 落盘 + 请求 ID 串联 + 尾部检索，替代 ELK 的轻量方案。

- 访问日志与业务事件统一写入 ``.runtime/logs/app.jsonl``，每行一个 JSON；
- 超过 ``LOG_MAX_BYTES`` 按 ``app.jsonl.1`` 方式滚动，保留 ``LOG_BACKUP_COUNT`` 份；
- ``tail()`` 读取最近日志用于管理端检索（按级别/模块/关键字过滤），不必引入日志中心。
"""
from __future__ import annotations

import json
import threading
from collections import deque
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from .config import LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

_lock = threading.Lock()
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str) -> None:
    _request_id.set(value or "-")


def get_request_id() -> str:
    return _request_id.get()


def _rotate_locked() -> None:
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size < LOG_MAX_BYTES:
        return
    for index in range(LOG_BACKUP_COUNT - 1, 0, -1):
        src = LOG_FILE.with_name(f"{LOG_FILE.name}.{index}")
        dst = LOG_FILE.with_name(f"{LOG_FILE.name}.{index + 1}")
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.rename(dst)
    first = LOG_FILE.with_name(f"{LOG_FILE.name}.1")
    if first.exists():
        first.unlink()
    LOG_FILE.rename(first)


def log_event(level: str, event: str, **fields) -> None:
    """写一条结构化日志；异常只影响日志本身，不影响业务。"""
    record = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "level": (level or "info").upper(),
        "event": event,
        "request_id": get_request_id(),
    }
    for key, value in fields.items():
        if value is None:
            continue
        record[key] = value if isinstance(value, (int, float, bool)) else str(value)[:512]
    line = json.dumps(record, ensure_ascii=False)
    try:
        with _lock:
            _rotate_locked()
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:  # pragma: no cover - 磁盘异常时放弃日志
        pass


def _iter_lines(limit_files: int = 3):
    """按时间正序产出最近若干文件的日志行。"""
    files = [LOG_FILE] + [LOG_FILE.with_name(f"{LOG_FILE.name}.{i}") for i in range(1, limit_files + 1)]
    for path in reversed(files):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    yield line
        except OSError:  # pragma: no cover
            continue


def tail(limit: int = 100, level: str | None = None, module: str | None = None, keyword: str | None = None) -> list[dict]:
    """返回最多 ``limit`` 条最近日志（新的在前）。"""
    limit = max(1, min(int(limit or 100), 500))
    level = (level or "").strip().upper()
    module = (module or "").strip()
    keyword = (keyword or "").strip()
    buffer: deque[dict] = deque(maxlen=limit)
    for line in _iter_lines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if level and str(record.get("level", "")).upper() != level:
            continue
        if module and module not in str(record.get("event", "")) and module not in str(record.get("path", "")):
            continue
        if keyword and keyword not in line:
            continue
        buffer.append(record)
    return list(reversed(buffer))


def stats() -> dict:
    """日志文件与条数概况。"""
    files = []
    total = 0
    for path in sorted(LOG_FILE.parent.glob(f"{LOG_FILE.name}*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        files.append({"name": path.name, "size": size})
    return {
        "path": str(Path(LOG_FILE)),
        "files": files,
        "total_bytes": total,
        "max_bytes": LOG_MAX_BYTES,
        "backup_count": LOG_BACKUP_COUNT,
    }
