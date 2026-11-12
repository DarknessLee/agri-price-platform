"""站内通知中心接口（契约 M2 §4）。

登录即可访问；可见范围为本人通知（``user_id``）与全员广播（``user_id=0``）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..responses import ok
from ..security import CurrentUser
from ..services import notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    user: CurrentUser,
    db: Session = Depends(get_db),
    unread_only: bool = Query(default=False),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """通知列表：分页、未读过滤、分类过滤；返回 list/total/unread/page/page_size。"""
    items, total, unread = notification.list_notifications(
        db,
        int(user.id),
        unread_only=bool(unread_only),
        category=category,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "list": items,
            "total": total,
            "unread": unread,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/summary")
def notifications_summary(user: CurrentUser, db: Session = Depends(get_db)):
    """未读总数与按分类的未读分布。"""
    return ok(notification.summary(db, int(user.id)))


@router.post("/read-all")
def notifications_read_all(user: CurrentUser, db: Session = Depends(get_db)):
    """把当前用户可见的未读通知全部置为已读。"""
    updated = notification.mark_all_read(db, int(user.id))
    return ok({"updated": updated})


@router.post("/{notification_id}/read")
def notifications_read(
    notification_id: int,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """把单条通知标记为已读。"""
    return ok(notification.mark_read(db, int(user.id), notification_id))
