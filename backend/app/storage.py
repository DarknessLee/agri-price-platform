"""对象存储抽象层：默认写入本地 MinIO（S3 兼容），不可用时降级到本地文件系统。

设计要点：
- 业务侧只使用对象键（如 ``reports/report_12_daily.html``），不关心落在 MinIO 还是磁盘；
- MinIO 采用惰性连接：首次使用时探测，失败后冷却 30 秒再重试，期间走本地目录，避免拖慢接口；
- 所有方法都不抛异常给业务，读取失败返回 None，由调用方决定降级文案。
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

from .config import (
    MINIO_ACCESS_KEY,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    STORAGE_BACKEND,
    STORAGE_BUCKET,
    STORAGE_ROOT,
)

_LOCK = threading.Lock()
_CLIENT = None
_MODE = "fs"
_LAST_ERROR = ""
_LAST_CHECK = 0.0
_COOLDOWN_SECONDS = 30


def _now() -> float:
    return time.time()


def _make_client():
    """构造 MinIO 客户端；import 放在函数内，缺少依赖时自动降级。"""
    import urllib3
    from minio import Minio  # type: ignore

    # minio 7.x 的 Minio() 不再接受 timeout 参数，超时需通过 http_client 传入。
    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=2.0, read=5.0),
        retries=urllib3.Retry(total=1, backoff_factor=0.2),
    )
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
        http_client=http_client,
    )


def _ensure_bucket(client) -> None:
    if not client.bucket_exists(STORAGE_BUCKET):
        client.make_bucket(STORAGE_BUCKET)


def _resolve_client():
    """返回可用的 MinIO 客户端；不可用时返回 None 并记录原因。"""
    global _CLIENT, _MODE, _LAST_ERROR, _LAST_CHECK
    if STORAGE_BACKEND != "minio":
        _MODE = "fs"
        return None
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        if _now() - _LAST_CHECK < _COOLDOWN_SECONDS:
            return None
        _LAST_CHECK = _now()
        try:
            client = _make_client()
            _ensure_bucket(client)
            _CLIENT = client
            _MODE = "minio"
            _LAST_ERROR = ""
            return client
        except Exception as exc:  # pragma: no cover - 取决于本地环境
            _CLIENT = None
            _MODE = "fs"
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
            return None


def backend_name() -> str:
    """当前实际生效的存储后端：minio 或 fs。"""
    if STORAGE_BACKEND != "minio":
        return "fs"
    return "minio" if _CLIENT is not None else "fs"


def configured_backend() -> str:
    return STORAGE_BACKEND


def _fs_path(key: str) -> Path:
    safe = key.replace("\\", "/").lstrip("/")
    path = (STORAGE_ROOT / safe).resolve()
    root = STORAGE_ROOT.resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"非法对象键：{key}")
    return path


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """写入对象，返回对象键。MinIO 失败时自动落盘并返回同一键。"""
    client = _resolve_client()
    if client is not None:
        try:
            client.put_object(
                STORAGE_BUCKET, key, io.BytesIO(data), length=len(data), content_type=content_type
            )
            return key
        except Exception:  # pragma: no cover - 网络/服务异常时降级
            global _CLIENT, _MODE, _LAST_ERROR
            _CLIENT = None
            _MODE = "fs"
            _LAST_ERROR = "minio put_object 失败，已降级本地目录"
    path = _fs_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def put_text(key: str, text: str, content_type: str = "text/plain; charset=utf-8") -> str:
    return put_bytes(key, text.encode("utf-8"), content_type)


def get_bytes(key: str) -> bytes | None:
    """读取对象；不存在或后端异常返回 None。"""
    if not key:
        return None
    client = _resolve_client()
    if client is not None:
        try:
            response = client.get_object(STORAGE_BUCKET, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:  # pragma: no cover - 对象不存在或服务异常
            pass
    try:
        path = _fs_path(key)
    except ValueError:
        return None
    return path.read_bytes() if path.is_file() else None


def get_text(key: str) -> str | None:
    data = get_bytes(key)
    if data is None:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def exists(key: str) -> bool:
    if not key:
        return False
    client = _resolve_client()
    if client is not None:
        try:
            client.stat_object(STORAGE_BUCKET, key)
            return True
        except Exception:  # pragma: no cover
            pass
    try:
        return _fs_path(key).is_file()
    except ValueError:
        return False


def delete(key: str) -> bool:
    if not key:
        return False
    ok = False
    client = _resolve_client()
    if client is not None:
        try:
            client.remove_object(STORAGE_BUCKET, key)
            ok = True
        except Exception:  # pragma: no cover
            ok = False
    try:
        path = _fs_path(key)
        if path.is_file():
            path.unlink()
            ok = True
    except ValueError:
        pass
    return ok


def stat(key: str) -> dict:
    """对象元信息：存在性、大小、后端。"""
    client = _resolve_client()
    if client is not None:
        try:
            info = client.stat_object(STORAGE_BUCKET, key)
            return {
                "key": key,
                "backend": "minio",
                "exists": True,
                "size": int(info.size or 0),
                "content_type": info.content_type or "",
            }
        except Exception:  # pragma: no cover
            pass
    try:
        path = _fs_path(key)
    except ValueError:
        return {"key": key, "backend": "fs", "exists": False, "size": 0, "content_type": ""}
    if path.is_file():
        return {"key": key, "backend": "fs", "exists": True, "size": path.stat().st_size, "content_type": ""}
    return {"key": key, "backend": "fs", "exists": False, "size": 0, "content_type": ""}


def health() -> dict:
    """存储健康状态：探测 MinIO 是否可用（带冷却，避免每次请求都连）。"""
    client = _resolve_client()
    ok = client is not None
    return {
        "configured": STORAGE_BACKEND,
        "backend": "minio" if ok else "fs",
        "ok": True,  # 本地回退始终可写
        "bucket": STORAGE_BUCKET if ok else "",
        "endpoint": MINIO_ENDPOINT if STORAGE_BACKEND == "minio" else str(STORAGE_ROOT),
        "degraded": STORAGE_BACKEND == "minio" and not ok,
        "error": _LAST_ERROR if STORAGE_BACKEND == "minio" and not ok else "",
    }


def count_objects(limit: int = 2000) -> int:
    """统计桶内对象数量（达到 limit 即返回，避免大桶全量列举拖慢监控页）。"""
    client = _resolve_client()
    if client is not None:
        try:
            total = 0
            for _ in client.list_objects(STORAGE_BUCKET, recursive=True):
                total += 1
                if total >= limit:
                    return limit
            return total
        except Exception:  # pragma: no cover - 列举失败时回退本地计数
            pass
    try:
        if not STORAGE_ROOT.exists():
            return 0
        return sum(1 for p in STORAGE_ROOT.rglob("*") if p.is_file())
    except Exception:  # pragma: no cover
        return 0


def report_key(report_id: int, report_type: str) -> str:
    """报告正文的对象键，保持与历史文件名一致，便于迁移。"""
    return f"reports/report_{int(report_id)}_{report_type}.html"


def import_key(task_id: int, filename: str) -> str:
    safe = (filename or "upload.csv").replace("/", "_").replace("\\", "_")
    return f"imports/{int(task_id)}_{safe}"


def model_key(variety_id: int, region_id: int, algorithm: str, version: str) -> str:
    return f"models/{variety_id}_{region_id}_{algorithm}_{version}.json"
