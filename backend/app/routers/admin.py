"""后台管理接口（契约 §11）：用户、角色权限、基础数据、审计日志、调度任务、系统信息。"""
from __future__ import annotations

import platform
import time
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION, DB_PATH, HOST, PORT
from ..database import get_db, now
from ..models import (
    AuditLog,
    Permission,
    PriceRecord,
    Region,
    Role,
    RolePermission,
    ScheduledTask,
    ScheduledTaskRun,
    User,
    Variety,
)
from ..responses import ok, page_args, paged
from ..security import ApiError, CurrentUser, client_ip, hash_password, require_permission, write_audit
from ..services import notification, quality, tasks as task_service

router = APIRouter(tags=["后台管理"])

USER_STATUS = ("启用", "停用")
PASSWORD_MIN_LENGTH = 8
RESERVED_ROLE = "admin"
MODULE_BASE = "基础数据"
MODULE_ADMIN = "后台管理"


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #

def _fmt_time(value) -> str | None:
    """时间 -> YYYY-MM-DDTHH:MM:SS。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _parse_time(value, field: str) -> datetime | None:
    """解析筛选时间，支持日期或完整时间。"""
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ApiError("E4001", f"{field}格式不正确，应为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS")


def _check_password(password: str) -> str:
    """口令强度校验。"""
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise ApiError("E4001", f"密码长度不能少于 {PASSWORD_MIN_LENGTH} 位")
    return password


def _get_role(db: Session, role_key: str) -> Role:
    """按 key 取角色，不存在返回 404。"""
    role = db.get(Role, (role_key or "").strip())
    if not role:
        raise ApiError("E4040", "角色不存在", 404)
    return role


def _user_item(user: User, role_name: str) -> dict:
    """用户 -> 契约结构。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role_key": user.role_key,
        "role_name": role_name,
        "org": user.org,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
        "last_login_at": _fmt_time(user.last_login_at),
    }


def _role_names(db: Session) -> dict[str, str]:
    """角色 key -> 名称映射。"""
    return {role.key: role.name for role in db.execute(select(Role)).scalars().all()}


# --------------------------------------------------------------------------- #
# 用户管理
# --------------------------------------------------------------------------- #

class UserCreateBody(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role_key: str = "viewer"
    org: str = ""
    phone: str = ""
    email: str = ""


class UserUpdateBody(BaseModel):
    display_name: str | None = None
    role_key: str | None = None
    org: str | None = None
    phone: str | None = None
    email: str | None = None
    status: str | None = None


class ResetPasswordBody(BaseModel):
    password: str


@router.get("/users")
def list_users(
    keyword: str | None = Query(default=None, description="用户名/姓名/机构/手机/邮箱"),
    role_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _perm: object = Depends(require_permission("admin:user")),
    db: Session = Depends(get_db),
):
    """用户分页列表。"""
    page, page_size = page_args(page, page_size)
    conds = []
    if keyword:
        like = f"%{keyword.strip()}%"
        conds.append(
            or_(
                User.username.like(like),
                User.display_name.like(like),
                User.org.like(like),
                User.phone.like(like),
                User.email.like(like),
            )
        )
    if role_key:
        conds.append(User.role_key == role_key)
    if status:
        if status not in USER_STATUS:
            raise ApiError("E4001", "用户状态仅支持启用、停用")
        conds.append(User.status == status)
    total = int(db.execute(select(func.count(User.id)).where(*conds)).scalar() or 0)
    users = (
        db.execute(
            select(User)
            .where(*conds)
            .order_by(User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    names = _role_names(db)
    return paged(
        [_user_item(user, names.get(user.role_key, user.role_key)) for user in users],
        total,
        page,
        page_size,
    )


@router.post("/users")
def create_user(
    body: UserCreateBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:user")),
    db: Session = Depends(get_db),
):
    """新增用户。"""
    username = (body.username or "").strip()
    if not username or len(username) < 3 or len(username) > 32:
        raise ApiError("E4001", "用户名长度应为 3-32 位")
    if not all(char.isalnum() or char in "_.-" for char in username):
        raise ApiError("E4001", "用户名仅支持字母、数字、下划线、点和短横线")
    _check_password(body.password)
    _get_role(db, body.role_key)
    exists = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if exists:
        raise ApiError("E4090", "用户名已存在", 409)
    created = User(
        username=username,
        password_hash=hash_password(body.password),
        display_name=(body.display_name or username).strip()[:64],
        role_key=body.role_key,
        org=(body.org or "")[:128],
        phone=(body.phone or "")[:32],
        email=(body.email or "")[:128],
        status="启用",
        created_at=now(),
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    write_audit(
        db, user, "新增", MODULE_ADMIN, f"新增用户 {created.username}（{created.role_key}）", client_ip(request)
    )
    return ok(_user_item(created, _role_names(db).get(created.role_key, created.role_key)))


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdateBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:user")),
    db: Session = Depends(get_db),
):
    """编辑用户。"""
    target = db.get(User, int(user_id or 0))
    if not target:
        raise ApiError("E4040", "用户不存在", 404)
    payload = body.model_dump(exclude_unset=True)
    if "role_key" in payload and payload["role_key"]:
        _get_role(db, payload["role_key"])
        if target.id == user.id and payload["role_key"] != target.role_key:
            raise ApiError("E4002", "不能修改当前登录账号的角色")
        target.role_key = payload["role_key"]
    if "status" in payload and payload["status"]:
        if payload["status"] not in USER_STATUS:
            raise ApiError("E4001", "用户状态仅支持启用、停用")
        if target.id == user.id and payload["status"] != "启用":
            raise ApiError("E4002", "不能停用当前登录账号")
        target.status = payload["status"]
    for field, limit in (("display_name", 64), ("org", 128), ("phone", 32), ("email", 128)):
        if field in payload and payload[field] is not None:
            setattr(target, field, str(payload[field])[:limit])
    db.commit()
    db.refresh(target)
    write_audit(
        db, user, "编辑", MODULE_ADMIN, f"编辑用户 {target.username}", client_ip(request)
    )
    return ok(_user_item(target, _role_names(db).get(target.role_key, target.role_key)))


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:user")),
    db: Session = Depends(get_db),
):
    """重置用户口令。"""
    target = db.get(User, int(user_id or 0))
    if not target:
        raise ApiError("E4040", "用户不存在", 404)
    _check_password(body.password)
    target.password_hash = hash_password(body.password)
    db.commit()
    write_audit(
        db, user, "重置密码", MODULE_ADMIN, f"重置用户 {target.username} 的登录密码", client_ip(request)
    )
    return ok({"ok": True})


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:user")),
    db: Session = Depends(get_db),
):
    """删除用户（保留至少一名管理员，且不能删除当前登录账号）。"""
    target = db.get(User, int(user_id or 0))
    if not target:
        raise ApiError("E4040", "用户不存在", 404)
    if target.id == user.id:
        raise ApiError("E4002", "不能删除当前登录账号")
    if target.role_key == RESERVED_ROLE:
        admins = int(
            db.execute(
                select(func.count(User.id)).where(User.role_key == RESERVED_ROLE)
            ).scalar()
            or 0
        )
        if admins <= 1:
            raise ApiError("E4002", "系统至少保留一名系统管理员")
    username = target.username
    db.delete(target)
    db.commit()
    write_audit(db, user, "删除", MODULE_ADMIN, f"删除用户 {username}", client_ip(request))
    return ok({"ok": True})


# --------------------------------------------------------------------------- #
# 角色与权限
# --------------------------------------------------------------------------- #

class RolePermissionsBody(BaseModel):
    permissions: list[str] = []


@router.get("/roles")
def list_roles(
    _perm: object = Depends(require_permission("admin:role")),
    db: Session = Depends(get_db),
):
    """角色列表（含权限点与用户数）。"""
    roles = db.execute(select(Role)).scalars().all()
    user_counts = {
        str(row[0]): int(row[1])
        for row in db.execute(select(User.role_key, func.count(User.id)).group_by(User.role_key)).all()
    }
    perm_rows = db.execute(
        select(RolePermission.role_key, RolePermission.perm_key)
        .join(Permission, Permission.key == RolePermission.perm_key)
        .order_by(Permission.module, Permission.sort, Permission.key)
    ).all()
    perms_by_role: dict[str, list[str]] = {}
    for role_key, perm_key in perm_rows:
        perms_by_role.setdefault(str(role_key), []).append(str(perm_key))
    order = {"admin": 0, "analyst": 1, "operator": 2, "viewer": 3}
    roles.sort(key=lambda role: (order.get(role.key, 99), role.key))
    return ok(
        [
            {
                "key": role.key,
                "name": role.name,
                "description": role.description,
                "user_count": user_counts.get(role.key, 0),
                "permissions": perms_by_role.get(role.key, []),
            }
            for role in roles
        ]
    )


@router.get("/permissions")
def list_permissions(
    _perm: object = Depends(require_permission("admin:role")),
    db: Session = Depends(get_db),
):
    """权限点清单（按模块分组排序）。"""
    rows = (
        db.execute(select(Permission).order_by(Permission.module, Permission.sort, Permission.key))
        .scalars()
        .all()
    )
    return ok(
        [{"key": item.key, "name": item.name, "module": item.module} for item in rows]
    )


@router.put("/roles/{role_key}/permissions")
def update_role_permissions(
    role_key: str,
    body: RolePermissionsBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:role")),
    db: Session = Depends(get_db),
):
    """保存角色的权限点集合。"""
    role = _get_role(db, role_key)
    requested = [str(key).strip() for key in body.permissions if str(key).strip()]
    valid_keys = {
        item for item in db.execute(select(Permission.key)).scalars().all()
    }
    unknown = [key for key in requested if key not in valid_keys]
    if unknown:
        raise ApiError("E4001", f"存在无效权限点：{'、'.join(unknown[:5])}")
    db.query(RolePermission).filter(RolePermission.role_key == role.key).delete(
        synchronize_session=False
    )
    for perm_key in dict.fromkeys(requested):
        db.add(RolePermission(role_key=role.key, perm_key=perm_key))
    db.commit()
    saved = list(
        dict.fromkeys(requested)
    )
    write_audit(
        db,
        user,
        "配置权限",
        MODULE_ADMIN,
        f"更新角色 {role.name} 的权限点（{len(saved)} 个）",
        client_ip(request),
    )
    return ok({"ok": True, "permissions": saved})


# --------------------------------------------------------------------------- #
# 审计日志
# --------------------------------------------------------------------------- #

@router.get("/audit-logs")
def list_audit_logs(
    username: str | None = Query(default=None),
    module: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _perm: object = Depends(require_permission("admin:audit")),
    db: Session = Depends(get_db),
):
    """审计日志分页列表。"""
    page, page_size = page_args(page, page_size)
    conds = []
    if username:
        conds.append(AuditLog.username.like(f"%{username.strip()}%"))
    if module:
        conds.append(AuditLog.module == module.strip())
    start_time = _parse_time(start, "开始时间")
    end_time = _parse_time(end, "结束时间")
    if start_time:
        conds.append(AuditLog.created_at >= start_time)
    if end_time:
        conds.append(AuditLog.created_at <= end_time)
    total = int(db.execute(select(func.count(AuditLog.id)).where(*conds)).scalar() or 0)
    logs = (
        db.execute(
            select(AuditLog)
            .where(*conds)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    items = [
        {
            "id": log.id,
            "username": log.username,
            "action": log.action,
            "module": log.module,
            "detail": log.detail,
            "ip": log.ip,
            "created_at": _fmt_time(log.created_at),
        }
        for log in logs
    ]
    return paged(items, total, page, page_size)


# --------------------------------------------------------------------------- #
# 调度任务
# --------------------------------------------------------------------------- #

def _task_item(task: ScheduledTask) -> dict:
    """调度任务 -> 契约结构。"""
    return {
        "id": task.id,
        "key": task.key,
        "name": task.name,
        "cron": task.cron,
        "cron_text": _cron_text(task.cron),
        "status": task.status,
        "last_run_at": _fmt_time(task.last_run_at),
        "last_result": task.last_result,
        "next_run_at": _fmt_time(task.next_run_at),
        "description": task.description,
    }


def _cron_text(expr: str) -> str:
    from .. import scheduler

    try:
        return scheduler.describe(expr)
    except Exception:  # pragma: no cover
        return str(expr)


def _run_task(db: Session, task: ScheduledTask, operator: str = "system", trigger: str = "手动") -> dict:
    """执行任务并返回执行结果（真实动作由 services.tasks 承担）。"""
    outcome = task_service.execute(db, task, trigger=trigger, operator=operator)
    return outcome


@router.get("/tasks")
def list_tasks(
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """调度任务列表。"""
    rows = db.execute(
        select(ScheduledTask, func.count(ScheduledTaskRun.id))
        .outerjoin(ScheduledTaskRun, ScheduledTaskRun.task_id == ScheduledTask.id)
        .group_by(ScheduledTask.id)
        .order_by(ScheduledTask.id)
    ).all()
    items = []
    for task, runs in rows:
        item = _task_item(task)
        item["runs"] = int(runs or 0)
        items.append(item)
    return ok(items)


@router.get("/tasks/runs")
def list_all_runs(
    status: str | None = Query(default=None),
    key: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """全局任务运行史（最近在前）。"""
    page, page_size = page_args(page, page_size)
    stmt = select(ScheduledTaskRun)
    if status:
        stmt = stmt.where(ScheduledTaskRun.status == status)
    if key:
        stmt = stmt.where(ScheduledTaskRun.task_key == key)
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0)
    rows = (
        db.execute(
            stmt.order_by(ScheduledTaskRun.started_at.desc(), ScheduledTaskRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return paged([task_service.serialize_run(row) for row in rows], total, page, page_size)


@router.get("/tasks/{task_id}/runs")
def list_task_runs(
    task_id: int,
    page: int = Query(default=1),
    page_size: int = Query(default=10),
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """单个任务的运行史。"""
    task = db.get(ScheduledTask, int(task_id or 0))
    if not task:
        raise ApiError("E4040", "调度任务不存在", 404)
    page, page_size = page_args(page, page_size)
    total = int(
        db.execute(
            select(func.count(ScheduledTaskRun.id)).where(ScheduledTaskRun.task_id == task.id)
        ).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.task_id == task.id)
            .order_by(ScheduledTaskRun.started_at.desc(), ScheduledTaskRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return paged([task_service.serialize_run(row) for row in rows], total, page, page_size)


@router.post("/tasks/tick")
def tick_tasks(
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """立即检查并执行到期任务（等价于调度器一次心跳）。"""
    from .. import scheduler

    result = scheduler.run_due()
    write_audit(
        db,
        user,
        "触发调度",
        MODULE_ADMIN,
        f"手动触发调度检查：到期 {result.get('checked', 0)} 个，执行 {result.get('triggered', 0)} 个",
        client_ip(request),
    )
    return ok(result)


@router.post("/tasks/{task_id}/run")
def run_task(
    task_id: int,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """立即执行调度任务。"""
    task = db.get(ScheduledTask, int(task_id or 0))
    if not task:
        raise ApiError("E4040", "调度任务不存在", 404)
    outcome = _run_task(db, task, operator=user.username, trigger="手动")
    write_audit(
        db,
        user,
        "执行任务",
        MODULE_ADMIN,
        f"手动执行任务 {task.name}：{outcome.get('result', '')[:120]}",
        client_ip(request),
    )
    return ok(
        {
            "ok": outcome.get("status") == "成功",
            "status": outcome.get("status"),
            "result": outcome.get("result"),
            "duration_ms": outcome.get("duration_ms"),
            "run_id": outcome.get("run_id"),
            "next_run_at": _fmt_time(task.next_run_at),
        }
    )


@router.post("/tasks/{task_id}/toggle")
def toggle_task(
    task_id: int,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:task")),
    db: Session = Depends(get_db),
):
    """启用/暂停调度任务。"""
    task = db.get(ScheduledTask, int(task_id or 0))
    if not task:
        raise ApiError("E4040", "调度任务不存在", 404)
    task.status = "暂停" if task.status == "启用" else "启用"
    db.commit()
    db.refresh(task)
    write_audit(
        db, user, "启停任务", MODULE_ADMIN, f"将任务 {task.name} 设置为{task.status}", client_ip(request)
    )
    return ok({"ok": True, "status": task.status})


# --------------------------------------------------------------------------- #
# 系统信息
# --------------------------------------------------------------------------- #

@router.get("/system/info")
def system_info(user: CurrentUser, db: Session = Depends(get_db)):
    """系统运行信息。"""
    from .. import scheduler, storage
    from ..config import DATABASE_URL, IS_SQLITE, MAIL_ENABLED, MAIL_HOST, MAIL_PORT
    from ..main import STARTED_AT

    started_at = datetime.fromtimestamp(STARTED_AT).replace(microsecond=0)
    uptime = max(int(time.time() - STARTED_AT), 0)
    if IS_SQLITE:
        db_text = f"SQLite（{DB_PATH.name}）"
    else:
        db_text = "MySQL 8（" + DATABASE_URL.split("@")[-1].split("?")[0] + "）"
    return ok(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "backend": f"FastAPI / Python {platform.python_version()}",
            "db": db_text,
            "python": platform.python_version(),
            "started_at": _fmt_time(started_at),
            "uptime_seconds": uptime,
            "port": PORT,
            "host": HOST,
            "user": user.display_name or user.username,
            "storage": storage.health(),
            "scheduler": scheduler.status(),
            "mail": {
                "enabled": MAIL_ENABLED,
                "endpoint": f"{MAIL_HOST}:{MAIL_PORT}",
                "web_ui": "http://127.0.0.1:8025" if MAIL_ENABLED else "",
            },
        }
    )


# --------------------------------------------------------------------------- #
# 基础数据：品种
# --------------------------------------------------------------------------- #

class VarietyBody(BaseModel):
    code: str | None = None
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    enabled: bool | None = None


def _variety_item(variety: Variety, record_count: int | None = None) -> dict:
    """品种 -> 契约结构。"""
    return {
        "id": variety.id,
        "code": variety.code,
        "name": variety.name,
        "category": variety.category,
        "unit": variety.unit,
        "enabled": bool(variety.enabled),
        "record_count": record_count,
    }


@router.get("/admin/varieties")
def list_varieties(
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """品种列表。"""
    counts = {
        int(row[0]): int(row[1])
        for row in db.execute(
            select(PriceRecord.variety_id, func.count(PriceRecord.id)).group_by(
                PriceRecord.variety_id
            )
        ).all()
    }
    varieties = db.execute(select(Variety).order_by(Variety.sort, Variety.id)).scalars().all()
    return ok([_variety_item(variety, counts.get(variety.id, 0)) for variety in varieties])


@router.post("/admin/varieties")
def create_variety(
    body: VarietyBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """新增品种。"""
    code = (body.code or "").strip()
    name = (body.name or "").strip()
    category = (body.category or "").strip()
    if not code or not name or not category:
        raise ApiError("E4001", "品种编码、名称、品类均不能为空")
    exists = db.execute(select(Variety).where(Variety.code == code)).scalar_one_or_none()
    if exists:
        raise ApiError("E4090", "品种编码已存在", 409)
    max_sort = db.execute(select(func.max(Variety.sort))).scalar() or 0
    variety = Variety(
        code=code[:32],
        name=name[:64],
        category=category[:32],
        unit=(body.unit or "元/公斤")[:16],
        enabled=True if body.enabled is None else bool(body.enabled),
        sort=int(max_sort) + 1,
    )
    db.add(variety)
    db.commit()
    db.refresh(variety)
    write_audit(db, user, "新增", MODULE_BASE, f"新增品种 {variety.name}", client_ip(request))
    return ok(_variety_item(variety, 0))


@router.put("/admin/varieties/{variety_id}")
def update_variety(
    variety_id: int,
    body: VarietyBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """编辑品种。"""
    variety = db.get(Variety, int(variety_id or 0))
    if not variety:
        raise ApiError("E4040", "品种不存在", 404)
    payload = body.model_dump(exclude_unset=True)
    if payload.get("code"):
        code = str(payload["code"]).strip()
        duplicate = db.execute(
            select(Variety).where(Variety.code == code, Variety.id != variety.id)
        ).scalar_one_or_none()
        if duplicate:
            raise ApiError("E4090", "品种编码已存在", 409)
        variety.code = code[:32]
    if payload.get("name"):
        variety.name = str(payload["name"]).strip()[:64]
    if payload.get("category"):
        variety.category = str(payload["category"]).strip()[:32]
    if payload.get("unit") is not None and payload.get("unit") != "":
        variety.unit = str(payload["unit"])[:16]
    if payload.get("enabled") is not None:
        variety.enabled = bool(payload["enabled"])
    db.commit()
    db.refresh(variety)
    write_audit(db, user, "编辑", MODULE_BASE, f"编辑品种 {variety.name}", client_ip(request))
    count = int(
        db.execute(
            select(func.count(PriceRecord.id)).where(PriceRecord.variety_id == variety.id)
        ).scalar()
        or 0
    )
    return ok(_variety_item(variety, count))


# --------------------------------------------------------------------------- #
# 基础数据：地区
# --------------------------------------------------------------------------- #

class RegionBody(BaseModel):
    code: str | None = None
    name: str | None = None
    level: str | None = None
    enabled: bool | None = None


def _region_item(region: Region, record_count: int | None = None) -> dict:
    """地区 -> 契约结构。"""
    return {
        "id": region.id,
        "code": region.code,
        "name": region.name,
        "level": region.level,
        "enabled": bool(region.enabled),
        "record_count": record_count,
    }


@router.get("/admin/regions")
def list_regions(
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """地区列表。"""
    counts = {
        int(row[0]): int(row[1])
        for row in db.execute(
            select(PriceRecord.region_id, func.count(PriceRecord.id)).group_by(
                PriceRecord.region_id
            )
        ).all()
    }
    regions = db.execute(select(Region).order_by(Region.sort, Region.id)).scalars().all()
    return ok([_region_item(region, counts.get(region.id, 0)) for region in regions])


@router.post("/admin/regions")
def create_region(
    body: RegionBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """新增地区。"""
    code = (body.code or "").strip()
    name = (body.name or "").strip()
    if not code or not name:
        raise ApiError("E4001", "地区编码、名称不能为空")
    exists = db.execute(select(Region).where(Region.code == code)).scalar_one_or_none()
    if exists:
        raise ApiError("E4090", "地区编码已存在", 409)
    max_sort = db.execute(select(func.max(Region.sort))).scalar() or 0
    region = Region(
        code=code[:32],
        name=name[:64],
        level=(body.level or "省级")[:16],
        enabled=True if body.enabled is None else bool(body.enabled),
        sort=int(max_sort) + 1,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    write_audit(db, user, "新增", MODULE_BASE, f"新增地区 {region.name}", client_ip(request))
    return ok(_region_item(region, 0))


@router.put("/admin/regions/{region_id}")
def update_region(
    region_id: int,
    body: RegionBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("admin:base")),
    db: Session = Depends(get_db),
):
    """编辑地区。"""
    region = db.get(Region, int(region_id or 0))
    if not region:
        raise ApiError("E4040", "地区不存在", 404)
    payload = body.model_dump(exclude_unset=True)
    if payload.get("code"):
        code = str(payload["code"]).strip()
        duplicate = db.execute(
            select(Region).where(Region.code == code, Region.id != region.id)
        ).scalar_one_or_none()
        if duplicate:
            raise ApiError("E4090", "地区编码已存在", 409)
        region.code = code[:32]
    if payload.get("name"):
        region.name = str(payload["name"]).strip()[:64]
    if payload.get("level"):
        region.level = str(payload["level"]).strip()[:16]
    if payload.get("enabled") is not None:
        region.enabled = bool(payload["enabled"])
    db.commit()
    db.refresh(region)
    write_audit(db, user, "编辑", MODULE_BASE, f"编辑地区 {region.name}", client_ip(request))
    count = int(
        db.execute(
            select(func.count(PriceRecord.id)).where(PriceRecord.region_id == region.id)
        ).scalar()
        or 0
    )
    return ok(_region_item(region, count))
