"""调度任务的真实执行器：把任务 key 映射到具体业务动作，并记录运行史。

历史实现只返回一句文案（"已提交""已执行"），无法验证任务是否真的跑过。这里每个 key 都调用
对应服务：同步价格统计、扫描预警、重训漂移模型、生成日报、巡检数据质量；每次执行写一条
``scheduled_task_run``，失败自动重试一次，并把结果回写到任务表与通知中心。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import TASK_RUN_RETENTION_DAYS
from ..models import DataSource, ModelVersion, PriceRecord, ScheduledTask, ScheduledTaskRun
from . import alerting, notification, quality, reporting

MAX_DURATION_MS = 1000 * 60 * 10


def _fmt(moment: datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "无"


def _sync_price(db: Session) -> str:
    """刷新数据源记录数与同步时间（真实统计价格表）。"""
    sources = db.execute(select(DataSource).order_by(DataSource.id)).scalars().all()
    total = 0
    for source in sources:
        count = int(
            db.execute(
                select(func.count(PriceRecord.id)).where(PriceRecord.source_id == source.id)
            ).scalar()
            or 0
        )
        source.record_count = count
        source.last_sync_at = datetime.now()
        total += count
    latest = db.execute(select(func.max(PriceRecord.price_date))).scalar()
    db.commit()
    return f"价格数据同步完成：{len(sources)} 个数据源，共 {total} 条价格记录，最新日期 {_fmt(latest)}"


def _alert_scan(db: Session) -> str:
    outcome = alerting.evaluate_rules(db, days=30)
    return (
        f"预警规则扫描完成：检查 {outcome.get('scanned', 0)} 条规则，"
        f"新增预警 {outcome.get('created', 0)} 条"
    )


def _model_retrain(db: Session) -> str:
    """按漂移程度挑选需要重训的模型组合，失败模型跳过并汇总。"""
    from . import governance, forecasting

    try:
        payload = governance.model_drift(db, window=90)
        items = payload.get("items", [])
    except Exception:  # 漂移计算失败则退回全量重训
        items = []
    drifted = [item for item in items if item.get("drift_level") == "漂移"][:5]
    if not drifted:
        rows = (
            db.execute(
                select(ModelVersion).where(ModelVersion.is_active.is_(True)).order_by(ModelVersion.mape.desc())
            )
            .scalars()
            .all()
        )
        pairs: list[tuple[int, int]] = []
        for model in rows:
            pair = (int(model.variety_id), int(model.region_id))
            if pair not in pairs:
                pairs.append(pair)
            if len(pairs) >= 5:
                break
        label = "按精度排序"
    else:
        pairs = [(int(item["variety_id"]), int(item["region_id"])) for item in drifted]
        label = "按漂移程度"
    trained = 0
    failed = 0
    for variety_id, region_id in pairs:
        try:
            forecasting.train_model(db, variety_id, region_id, commit=True, notify=False)
            trained += 1
        except Exception:
            db.rollback()
            failed += 1
    return f"模型重训完成（{label}）：成功 {trained} 组，失败 {failed} 组"


def _report_daily(db: Session) -> str:
    record = reporting.generate_report(db, None, report_type="daily")
    return f"日报生成完成：{record.title}（状态 {record.status}）"


def _quality_check(db: Session) -> str:
    summary = quality.summary(db)
    return (
        f"数据质量巡检完成：完整率 {summary.get('completeness', 0)}%，"
        f"异常记录 {summary.get('outlier_count', 0)} 条，总记录 {summary.get('total_records', 0)} 条"
    )


_ACTIONS = {
    "sync_price": _sync_price,
    "alert_scan": _alert_scan,
    "model_retrain": _model_retrain,
    "report_daily": _report_daily,
    "quality_check": _quality_check,
}


def _next_run_at(task: ScheduledTask, base: datetime | None = None) -> datetime | None:
    from .. import scheduler

    return scheduler.next_run(task.cron, base or datetime.now())


def _write_notice(db: Session, task: ScheduledTask, status: str, result: str) -> None:
    try:
        notification.broadcast(
            db,
            f"调度任务{'执行完成' if status == '成功' else '执行失败'}：{task.name}",
            result[:200],
            category="任务",
            level="低" if status == "成功" else "高",
            link="/admin/tasks",
            commit=True,
        )
    except Exception:
        db.rollback()


def execute(
    db: Session,
    task: ScheduledTask,
    trigger: str = "手动",
    operator: str = "system",
    retry: int = 1,
) -> dict:
    """执行一次任务并落库运行史；返回 {status, result, duration_ms, run_id}。"""
    started = datetime.now()
    attempts = 0
    status = "成功"
    result = ""
    error = ""
    while True:
        attempts += 1
        started = datetime.now()
        try:
            action = _ACTIONS.get(task.key)
            result = action(db) if action else "任务执行完成（未定义具体动作）"
            error = ""
            status = "成功"
            break
        except Exception as exc:
            db.rollback()
            error = f"{type(exc).__name__}: {exc}"
            status = "失败"
            result = f"执行失败：{error[:180]}"
            if attempts > max(0, retry):
                break
    duration_ms = int((datetime.now() - started).total_seconds() * 1000)

    finished = datetime.now()
    run = ScheduledTaskRun(
        task_id=task.id,
        task_key=task.key,
        task_name=task.name,
        trigger=trigger or "手动",
        status=status,
        result=result[:500],
        error=error[:500],
        duration_ms=duration_ms,
        started_at=started,
        finished_at=finished,
    )
    db.add(run)
    task.last_run_at = finished
    task.last_result = result[:255]
    task.next_run_at = _next_run_at(task, finished)
    try:
        db.commit()
    except Exception:
        db.rollback()
    db.refresh(run)

    _write_notice(db, task, status, result)
    _prune_runs(db)
    return {
        "status": status,
        "result": result,
        "duration_ms": duration_ms,
        "run_id": run.id,
        "next_run_at": task.next_run_at,
    }


def _prune_runs(db: Session) -> None:
    """清理超过保留天数的运行史，避免表无限增长。"""
    cutoff = datetime.now() - timedelta(days=TASK_RUN_RETENTION_DAYS)
    try:
        rows = (
            db.execute(select(ScheduledTaskRun).where(ScheduledTaskRun.started_at < cutoff))
            .scalars()
            .all()
        )
        for row in rows:
            db.delete(row)
        if rows:
            db.commit()
    except Exception:
        db.rollback()


def serialize_run(run: ScheduledTaskRun) -> dict:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "task_key": run.task_key,
        "task_name": run.task_name,
        "trigger": run.trigger,
        "status": run.status,
        "result": run.result,
        "error": run.error,
        "duration_ms": run.duration_ms,
        "started_at": run.started_at.strftime("%Y-%m-%dT%H:%M:%S") if run.started_at else "",
        "finished_at": run.finished_at.strftime("%Y-%m-%dT%H:%M:%S") if run.finished_at else "",
    }
