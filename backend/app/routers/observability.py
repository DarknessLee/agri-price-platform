"""可观测性接口（契约 M3 §2/§3）：日志检索、指标汇总、系统状态、邮件通道。

数据全部来自已落地的轻量组件——结构化日志 ``logging_setup``、进程内指标
``services.metrics``、调度器 ``scheduler``、对象存储 ``storage``、邮件 ``services.mailer``，
不依赖 ELK / Prometheus 等外部栈，保证单机验收环境开箱可用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import METRICS_WINDOW_MINUTES
from ..database import get_db, ping
from ..logging_setup import stats as log_stats
from ..logging_setup import tail as log_tail
from ..responses import ok
from ..security import CurrentUser, client_ip, require_permission, write_audit
from ..services import mailer, metrics

router = APIRouter(tags=["可观测性"])


# --------------------------------------------------------------------------- #
# 日志检索（契约 §2）
# --------------------------------------------------------------------------- #

@router.get("/logs")
def list_logs(
    limit: int = Query(100, ge=1, le=500, description="返回条数，上限 500"),
    level: str | None = Query(None, description="日志级别：INFO/WARN/ERROR"),
    module: str | None = Query(None, description="模块/事件关键字"),
    keyword: str | None = Query(None, description="全文关键字"),
    _user=Depends(require_permission("admin:audit")),
):
    """尾部检索结构化访问日志，返回最近记录与日志文件概况。"""
    items = log_tail(
        limit=limit,
        level=(level or "").strip() or None,
        module=(module or "").strip() or None,
        keyword=(keyword or "").strip() or None,
    )
    return ok({"list": items, "stats": log_stats()})


# --------------------------------------------------------------------------- #
# 指标（契约 §2）
# --------------------------------------------------------------------------- #

@router.get("/metrics/summary")
def metrics_summary(
    minutes: int = Query(METRICS_WINDOW_MINUTES, ge=1, le=1440, description="统计窗口（分钟）"),
    _user=Depends(require_permission("admin:task")),
):
    """最近 N 分钟 QPS/耗时分位/错误率/缓存命中/慢接口排行。"""
    return ok(metrics.summary(minutes))


@router.get("/metrics/timeseries")
def metrics_timeseries(
    minutes: int = Query(METRICS_WINDOW_MINUTES, ge=1, le=1440, description="统计窗口（分钟）"),
    _user=Depends(require_permission("admin:task")),
):
    """分钟级时序（缺失分钟补零），供监控页折线图使用。"""
    return ok(metrics.timeseries(minutes))


# --------------------------------------------------------------------------- #
# 系统状态（契约 §2，登录即可访问）
# --------------------------------------------------------------------------- #

@router.get("/system/status")
def system_status(_user: CurrentUser):
    """聚合数据库/缓存/存储/调度器/邮件/日志/指标的健康态与运行概况。"""
    from .. import scheduler, storage
    from ..cache import cache_available
    from ..main import STARTED_AT

    db_ok = ping()
    try:
        cache_ok = cache_available()
    except Exception:  # pragma: no cover - 缓存探测兜底
        cache_ok = False
    try:
        storage_state = storage.health()
    except Exception as exc:  # pragma: no cover - 存储探测兜底
        storage_state = {
            "configured": "",
            "backend": "fs",
            "ok": False,
            "bucket": "",
            "endpoint": "",
            "degraded": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        scheduler_state = scheduler.status()
    except Exception as exc:  # pragma: no cover
        scheduler_state = {"enabled": False, "running": False, "error": str(exc)}
    try:
        log_state = log_stats()
        logs_block = {
            "path": log_state.get("path", ""),
            "files": len(log_state.get("files") or []),
            "total_bytes": int(log_state.get("total_bytes") or 0),
        }
    except Exception:  # pragma: no cover
        logs_block = {"path": "", "files": 0, "total_bytes": 0}
    try:
        metric_state = metrics.summary(METRICS_WINDOW_MINUTES)
        metrics_block = {"window_minutes": METRICS_WINDOW_MINUTES, "total": int(metric_state.get("total") or 0)}
    except Exception:  # pragma: no cover
        metrics_block = {"window_minutes": METRICS_WINDOW_MINUTES, "total": 0}

    return ok(
        {
            "db": "ok" if db_ok else "error",
            "cache": "ok" if cache_ok else "error",
            "storage": storage_state,
            "scheduler": scheduler_state,
            "mail": mailer.health(),
            "logs": logs_block,
            "metrics": metrics_block,
            "uptime_seconds": max(int(datetime.now().timestamp() - STARTED_AT), 0),
            "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )


@router.get("/storage/health")
def storage_health(_user: Any = Depends(require_permission("admin:task"))):
    """对象存储健康态（契约 §5）：MinIO 不可用时返回 degraded 与具体错误。"""
    from .. import storage

    try:
        info = dict(storage.health())
    except Exception as exc:  # pragma: no cover - 探测兜底
        info = {
            "configured": "",
            "backend": "fs",
            "ok": False,
            "bucket": "",
            "endpoint": "",
            "degraded": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
    # 对象数量：MinIO 模式列举上限 2000，本地回退目录统计文件数，避免慢请求
    try:
        object_count = storage.count_objects()
    except Exception:  # pragma: no cover - 统计兜底
        object_count = 0
    return ok({**info, "object_count": object_count})


# --------------------------------------------------------------------------- #
# 邮件通道（契约 §3）
# --------------------------------------------------------------------------- #

@router.get("/mail/logs")
def mail_logs(
    limit: int = Query(20, ge=1, le=200),
    status: str | None = Query(None, description="已发送/失败"),
    _user=Depends(require_permission("admin:task")),
):
    """最近邮件发送记录（成功/失败计数齐全）。"""
    return ok(mailer.logs(limit=limit, status=status))


class MailTestBody(BaseModel):
    to: str | None = None


@router.post("/mail/test")
def mail_test(
    request: Request,
    body: MailTestBody | None = None,
    user: Any = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """发送连通性测试邮件；SMTP 不可达时返回 sent=false 并落失败原因，不抛 500。"""
    to_addr = (body.to if body else None) or ""
    outcome = mailer.test(to=to_addr or None)
    try:
        write_audit(
            db,
            user,
            "测试",
            "邮件通道",
            f"收件人 {outcome['to']}，结果 {outcome['status']}",
            client_ip(request),
        )
    except Exception:  # 审计失败不影响测试结果
        pass
    return ok(outcome)
