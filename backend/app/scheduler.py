"""进程内调度器：标准 5 段 cron 解析 + 守护线程按时触发，替代 Airflow 的轻量实现。

支持语法：``*``、``*/n``、``a``、``a-b``、``a-b/n``、``a,b,c`` 与 ``*`` 组合；日/周同时限定时
按标准 cron 语义取"或"关系。字段含义：分 时 日 月 周（0=周日 … 6=周六）。

相比外部调度系统，这里只有两件事：算出下次执行时间写入任务表，以及定时把到期任务交给
``services.tasks.execute`` 执行。服务重启后按库中的 ``next_run_at`` 续跑，不会丢任务。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from .config import SCHEDULER_ENABLED, SCHEDULER_TICK_SECONDS

_FIELD_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
_ALIASES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_stop_event = threading.Event()
_thread: threading.Thread | None = None
_last_tick: datetime | None = None
_last_result: dict = {}


def _parse_field(text: str, low: int, high: int) -> set[int] | None:
    text = (text or "").strip().lower()
    if not text:
        return None
    values: set[int] = set()
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            return None
        step = 1
        if "/" in chunk:
            chunk, _, step_text = chunk.partition("/")
            try:
                step = int(step_text)
            except ValueError:
                return None
            if step <= 0:
                return None
        if chunk in {"*", ""}:
            start, end = low, high
        elif "-" in chunk:
            left, _, right = chunk.partition("-")
            start, end = _token(left), _token(right)
            if start is None or end is None:
                return None
        else:
            start = _token(chunk)
            end = start if step == 1 else high
            if start is None:
                return None
        if start < low or end > high or start > end:
            return None
        values.update(range(start, end + 1, step))
    return values or None


def _token(text: str) -> int | None:
    text = (text or "").strip().lower()
    if text in _ALIASES:
        return _ALIASES[text]
    try:
        return int(text)
    except ValueError:
        return None


def parse(expr: str) -> dict | None:
    """解析 cron 表达式，非法返回 None。"""
    fields = (expr or "").split()
    if len(fields) != 5:
        return None
    parsed = []
    for text, (low, high) in zip(fields, _FIELD_RANGES):
        values = _parse_field(text, low, high)
        if not values:
            return None
        parsed.append(values)
    return {
        "minute": parsed[0],
        "hour": parsed[1],
        "day": parsed[2],
        "month": parsed[3],
        "weekday": parsed[4],
        "expression": " ".join(fields),
    }


def validate(expr: str) -> bool:
    return parse(expr) is not None


def describe(expr: str) -> str:
    """把 cron 翻译成中文说明，便于任务列表展示。"""
    spec = parse(expr)
    if spec is None:
        return "表达式无效"
    minute, hour, day, month, weekday = (
        spec["minute"], spec["hour"], spec["day"], spec["month"], spec["weekday"],
    )
    if minute == {0} and hour == {2} and weekday == {1} and day == set(range(1, 32)):
        return "每周一 02:00"
    if minute == {0} and len(hour) == 1:
        clock = f"{next(iter(hour)):02d}:00"
        if day == set(range(1, 32)) and weekday == set(range(0, 7)) and month == set(range(1, 13)):
            return f"每天 {clock}"
        if day == set(range(1, 32)) and len(weekday) == 1:
            names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
            return f"每{names[next(iter(weekday))]} {clock}"
    return f"自定义周期（{' '.join(str(expr).split())}）"


def next_run(expr: str, base: datetime | None = None, limit_days: int = 400) -> datetime | None:
    """计算下一次执行时间（严格晚于 base）。"""
    spec = parse(expr)
    if spec is None:
        return None
    base = (base or datetime.now()).replace(second=0, microsecond=0)
    start = base + timedelta(minutes=1)
    day_cursor = start.replace(hour=0, minute=0)
    full_day = spec["day"] == set(range(1, 32))
    full_week = spec["weekday"] == set(range(0, 7))
    for _ in range(limit_days):
        if (
            day_cursor.month in spec["month"]
            and (full_day or day_cursor.day in spec["day"])
            and (full_week or ((day_cursor.weekday() + 1) % 7) in spec["weekday"])
        ):
            for hour in sorted(spec["hour"]):
                for minute in sorted(spec["minute"]):
                    candidate = day_cursor.replace(hour=hour, minute=minute)
                    if candidate >= start:
                        return candidate
        day_cursor += timedelta(days=1)
    return None


def due_tasks(db, now: datetime | None = None) -> list:
    """返回当前到期的启用中任务（不执行）。"""
    from sqlalchemy import select

    from .models import ScheduledTask

    moment = now or datetime.now()
    rows = db.execute(select(ScheduledTask).order_by(ScheduledTask.id)).scalars().all()
    return [
        task
        for task in rows
        if task.status == "启用" and (task.next_run_at is None or task.next_run_at <= moment)
    ]


def run_due(now: datetime | None = None) -> dict:
    """执行所有到期任务，返回本次触发概况。"""
    from .database import SessionLocal
    from .services import tasks as task_service

    moment = now or datetime.now()
    triggered = 0
    failed = 0
    checked = 0
    details: list[dict] = []
    db = SessionLocal()
    try:
        due = due_tasks(db, moment)
        checked = len(due)
        for task in due:
            outcome = task_service.execute(db, task, trigger="定时", operator="scheduler")
            triggered += 1
            if outcome.get("status") != "成功":
                failed += 1
            details.append({"task": task.name, "status": outcome.get("status"), "result": outcome.get("result")})
    finally:
        db.close()
    return {"checked": checked, "due": checked, "triggered": triggered, "failed": failed, "details": details}


def _loop() -> None:
    global _last_tick, _last_result
    while not _stop_event.is_set():
        try:
            _last_result = run_due()
            _last_tick = datetime.now()
        except Exception as exc:  # 调度线程不能因单次异常退出
            _last_result = {"error": f"{type(exc).__name__}: {exc}"}
            _last_tick = datetime.now()
        _stop_event.wait(max(5, SCHEDULER_TICK_SECONDS))


def start() -> bool:
    """启动守护线程（重复调用幂等）。"""
    global _thread
    if not SCHEDULER_ENABLED:
        return False
    if _thread is not None and _thread.is_alive():
        return True
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="agri-scheduler", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop_event.set()


def status() -> dict:
    return {
        "enabled": SCHEDULER_ENABLED,
        "running": bool(_thread is not None and _thread.is_alive()),
        "tick_seconds": SCHEDULER_TICK_SECONDS,
        "last_tick_at": _last_tick.strftime("%Y-%m-%dT%H:%M:%S") if _last_tick else "",
        "last_result": _last_result,
        "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
