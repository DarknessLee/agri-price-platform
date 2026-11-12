"""认证与个人接口：登录、当前用户、退出、修改口令。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from ..responses import ok
from ..security import (
    ApiError,
    CurrentUser,
    client_ip,
    create_token,
    get_permissions,
    hash_password,
    revoke_token,
    verify_password,
    write_audit,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


def _user_brief(db: Session, user: User) -> dict:
    role = db.get(Role, user.role_key)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role_key": user.role_key,
        "role_name": role.name if role else user.role_key,
        "org": user.org,
        "phone": user.phone,
        "email": user.email,
        "status": user.status,
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else None,
    }


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == body.username.strip())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise ApiError("E4010", "用户名或密码不正确", 401)
    if user.status != "启用":
        raise ApiError("E4010", "账号已停用，请联系管理员", 401)
    token, expires_in = create_token(user)
    user.last_login_at = datetime.now().replace(microsecond=0)
    db.commit()
    write_audit(db, user, "登录", "认证", f"账号 {user.username} 登录系统", client_ip(request))
    return ok({
        "token": token,
        "expires_in": expires_in,
        "user": _user_brief(db, user),
        "permissions": get_permissions(db, user.role_key),
    })


@router.get("/me")
def me(user: CurrentUser, db: Session = Depends(get_db)):
    return ok({"user": _user_brief(db, user), "permissions": get_permissions(db, user.role_key)})


@router.post("/logout")
def logout(user: CurrentUser, request: Request, db: Session = Depends(get_db)):
    # 令牌加入 Redis 黑名单（TTL=剩余有效期）；Redis 不可用时静默降级
    revoke_token(request.headers.get("authorization"))
    write_audit(db, user, "退出", "认证", f"账号 {user.username} 退出登录", client_ip(request))
    return ok({"ok": True})


@router.put("/password")
def change_password(body: PasswordBody, user: CurrentUser, request: Request, db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise ApiError("E4001", "原密码不正确", 400)
    if len(body.new_password) < 8:
        raise ApiError("E4001", "新密码长度不能少于 8 位", 400)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    write_audit(db, user, "修改密码", "认证", f"账号 {user.username} 修改登录密码", client_ip(request))
    return ok({"ok": True})
