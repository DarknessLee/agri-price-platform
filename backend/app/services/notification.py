"""站内通知服务（契约 M2 §4）。

统一写库入口 ``create_notification`` 供各业务链路调用（预警产生/处置等），
并提供可见范围查询、未读统计与已读标记的公共实现，供 routers/notifications.py 复用。

可见范围：``user_id = 当前用户`` 或 ``user_id = 0``（全员广播）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from ..config import MAIL_ENABLED, MAIL_TO
from ..database import now
from ..models import Notification
from . import mailer

# 单次事件最多产生多少条广播通知，避免预警扫描批量命中时产生通知风暴
BROADCAST_LIMIT = 20

# 会话内待发送邮件队列的键：与业务同事务提交，提交成功才发信，回滚则丢弃
_PENDING_MAILS = "_agri_pending_mails"
PENDING_MAIL_LIMIT = 30


# ---------------------------------------------------------------- 邮件联动
# 契约 M3 §3：高等级预警、报告生成、任务失败、模型重训成功后发邮件。
# 邮件必须等业务事务真正提交后再发，避免"通知回滚了邮件却发出去"。

def should_send_mail(category: str, level: str, title: str = "") -> bool:
    """按通知分类/等级判断是否需要邮件外发。"""
    levels = mailer.alert_levels()
    category = str(category or "")
    level = str(level or "")
    if category == "预警":
        return level in levels
    if category == "报告":
        return True
    if category == "模型":
        return level != "高"  # 模型重训成功
    if category == "任务":
        return level in levels or "失败" in str(title or "")
    return False


def _queue_mail(db: Session, title: str, content: str, category: str, level: str, link: str) -> None:
    """把邮件挂到当前会话，``after_commit`` 时统一发出；关闭邮件通道时直接跳过。"""
    if not MAIL_ENABLED or not should_send_mail(category, level, title):
        return
    pending = db.info.setdefault(_PENDING_MAILS, [])
    if len(pending) >= PENDING_MAIL_LIMIT:
        return
    stamp = now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [str(title or ""), "", str(content or ""), "", f"时间：{stamp}", f"分类：{category}｜等级：{level}"]
    if link:
        lines.append(f"查看：http://127.0.0.1:5177{link}")
    pending.append(
        {
            "subject": f"[{category}] {title}"[:200],
            "body": "\n".join(lines)[:8000],
            "category": category,
        }
    )


@event.listens_for(Session, "after_commit")
def _flush_queued_mails(session: Session) -> None:
    """业务提交成功后再发信：发信失败只影响邮件记录，不影响已提交的业务。"""
    pending = session.info.pop(_PENDING_MAILS, None)
    if not pending:
        return
    for mail in pending:
        try:
            mailer.send_mail(
                to=MAIL_TO,
                subject=mail.get("subject", ""),
                body=mail.get("body", ""),
                category=mail.get("category", "系统"),
            )
        except Exception:  # pragma: no cover - mailer 内部已兜底，这里再保一层
            continue


@event.listens_for(Session, "after_rollback")
def _drop_queued_mails(session: Session) -> None:
    """事务回滚：丢弃对应的待发邮件，避免发送不存在的通知。"""
    session.info.pop(_PENDING_MAILS, None)


def create_notification(
    db: Session,
    user_id: int = 0,
    username: str = "",
    title: str = "",
    content: str = "",
    category: str = "系统",
    level: str = "低",
    link: str = "",
    created_at: Any = None,
    commit: bool = False,
) -> Notification:
    """写一条站内通知。

    ``user_id=0`` 表示全员可见；``commit=False`` 时由调用方统一提交（与业务同事务）。
    """
    row = Notification(
        user_id=int(user_id or 0),
        username=str(username or "")[:64],
        title=str(title or "")[:128],
        content=str(content or "")[:255],
        category=str(category or "系统")[:32],
        level=str(level or "低")[:8],
        link=str(link or "")[:128],
        created_at=created_at or now(),
        read_at=None,
    )
    db.add(row)
    db.flush()
    # 邮件与通知同事务排队：commit=True 提交后立即外发；commit=False 交由调用方提交时外发
    _queue_mail(db, row.title, row.content, row.category, row.level, row.link)
    if commit:
        db.commit()
    return row


def broadcast(
    db: Session,
    title: str,
    content: str = "",
    category: str = "系统",
    level: str = "低",
    link: str = "",
    commit: bool = False,
) -> Notification:
    """向全员（``user_id=0``）广播一条通知。"""
    return create_notification(
        db,
        user_id=0,
        username="系统",
        title=title,
        content=content,
        category=category,
        level=level,
        link=link,
        commit=commit,
    )


def notify_user(
    db: Session,
    user: Any,
    title: str,
    content: str = "",
    category: str = "系统",
    level: str = "低",
    link: str = "",
    commit: bool = False,
) -> Notification | None:
    """通知指定用户（``user`` 可为 User 对象或用户 id）；无法识别用户时返回 None。"""
    if user is None:
        return None
    if isinstance(user, int):
        user_id, username = int(user), ""
    else:
        user_id = int(getattr(user, "id", 0) or 0)
        username = str(getattr(user, "username", "") or "")
    if user_id <= 0:
        return None
    return create_notification(
        db,
        user_id=user_id,
        username=username,
        title=title,
        content=content,
        category=category,
        level=level,
        link=link,
        commit=commit,
    )


# ---------------------------------------------------------------- 查询

def _visible(user_id: int):
    """可见范围条件：本人通知或全员广播。"""
    return or_(Notification.user_id == int(user_id), Notification.user_id == 0)


def serialize_notification(row: Notification) -> dict:
    return {
        "id": int(row.id),
        "title": row.title or "",
        "content": row.content or "",
        "category": row.category or "系统",
        "level": row.level or "低",
        "link": row.link or "",
        "is_read": row.read_at is not None,
        "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S") if row.created_at else "",
    }


def list_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int, int]:
    """返回 (当前页列表, 过滤后总数, 可见未读数)。"""
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    conditions = [_visible(user_id)]
    if category:
        conditions.append(Notification.category == str(category))
    if unread_only:
        conditions.append(Notification.read_at.is_(None))

    total = int(db.execute(select(func.count(Notification.id)).where(*conditions)).scalar() or 0)
    unread = int(
        db.execute(
            select(func.count(Notification.id)).where(_visible(user_id), Notification.read_at.is_(None))
        ).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return [serialize_notification(row) for row in rows], total, unread


def summary(db: Session, user_id: int) -> dict:
    """未读总数与按分类的未读分布。"""
    unread = int(
        db.execute(
            select(func.count(Notification.id)).where(_visible(user_id), Notification.read_at.is_(None))
        ).scalar()
        or 0
    )
    by_category = [
        {"category": str(cat or "系统"), "count": int(count)}
        for cat, count in db.execute(
            select(Notification.category, func.count(Notification.id))
            .where(_visible(user_id), Notification.read_at.is_(None))
            .group_by(Notification.category)
            .order_by(func.count(Notification.id).desc(), Notification.category)
        ).all()
    ]
    return {"unread": unread, "by_category": by_category}


def mark_read(db: Session, user_id: int, notification_id: int) -> dict:
    """把一条可见通知标记为已读；不存在或不可见抛 E4040。"""
    from ..security import ApiError

    row = db.execute(
        select(Notification).where(Notification.id == int(notification_id), _visible(user_id))
    ).scalars().first()
    if row is None:
        raise ApiError("E4040", "通知不存在", 404)
    if row.read_at is None:
        row.read_at = now()
        db.add(row)
        db.commit()
    return {"id": int(row.id), "is_read": True}


def mark_all_read(db: Session, user_id: int) -> int:
    """把当前用户可见的未读通知全部标记为已读，返回更新条数。"""
    rows = db.execute(
        select(Notification).where(_visible(user_id), Notification.read_at.is_(None))
    ).scalars().all()
    if not rows:
        return 0
    stamp = now()
    for row in rows:
        row.read_at = stamp
        db.add(row)
    db.commit()
    return len(rows)
