"""鉴权与安全：PBKDF2 口令散列、HS256 JWT、当前用户与权限依赖、审计写入。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Annotated, Callable

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cache
from .config import SECRET_KEY, TOKEN_EXPIRE_MINUTES, TOKEN_ISSUER
from .database import get_db
from .models import AuditLog, RolePermission, User

PBKDF2_ROUNDS = 120_000


class ApiError(Exception):
    """统一业务异常：由 main.py 的错误处理器转为 {code,message,data}。"""

    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# ---------------------------- 口令 ----------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


# ---------------------------- JWT ----------------------------

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(user: User) -> tuple[str, int]:
    expire_at = datetime.now() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role_key,
        "iss": TOKEN_ISSUER,
        "iat": int(time.time()),
        "exp": int(expire_at.timestamp()),
        # 每次登录生成唯一令牌编号：同一秒内多次登录不会产生相同令牌，
        # 退出登录时按令牌指纹加入黑名单也不会误伤其他会话。
        "jti": secrets.token_hex(8),
    }
    segments = [
        _b64encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    return ".".join(segments + [_b64encode(signature)]), TOKEN_EXPIRE_MINUTES * 60


def decode_token(token: str) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
        actual = _b64decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            raise ApiError("E4010", "登录凭证已失效，请重新登录", 401)
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, binascii.Error, UnicodeEncodeError, json.JSONDecodeError):
        raise ApiError("E4010", "登录凭证格式不正确", 401)
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ApiError("E4010", "登录已过期，请重新登录", 401)
    return payload


# ---------------------------- 依赖 ----------------------------

def token_digest(token: str) -> str:
    """令牌指纹：sha256 十六进制，避免明文令牌落库/落缓存。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def blacklist_token(token: str) -> bool:
    """把令牌指纹写入 Redis 黑名单，TTL 取令牌剩余有效期；Redis 异常降级返回 False。"""
    try:
        payload = decode_token(token)
    except ApiError:
        return False
    remaining = int(payload.get("exp", 0)) - int(time.time())
    if remaining <= 0:
        return False
    return cache.set_raw(cache.blacklist_key(token_digest(token)), "1", ttl=remaining)


def is_token_blacklisted(token: str) -> bool:
    """令牌是否已注销；Redis 不可用时返回 False（降级放行）。"""
    return cache.exists(cache.blacklist_key(token_digest(token)))


def revoke_token(authorization: str | None) -> bool:
    """从 Authorization 头解析令牌并加入黑名单，供退出登录使用。"""
    try:
        token = _extract_token(authorization)
    except ApiError:
        return False
    return blacklist_token(token)


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        raise ApiError("E4010", "请先登录", 401)
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError("E4010", "登录凭证格式不正确", 401)
    return parts[1].strip()


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(authorization)
    payload = decode_token(token)
    if is_token_blacklisted(token):
        raise ApiError("E4010", "登录凭证已失效", 401)
    user = db.get(User, int(payload.get("sub", 0)))
    if not user or user.status != "启用":
        raise ApiError("E4010", "账号不存在或已停用", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_permissions(db: Session, role_key: str) -> list[str]:
    rows = db.execute(select(RolePermission.perm_key).where(RolePermission.role_key == role_key)).scalars().all()
    return sorted(rows)


def require_permission(*perms: str) -> Callable:
    """返回一个依赖：要求当前用户拥有其中任一权限点。"""

    def _checker(user: CurrentUser, db: Session = Depends(get_db)) -> User:
        owned = set(get_permissions(db, user.role_key))
        if not owned.intersection(perms):
            raise ApiError("E4030", "当前账号无权执行该操作", 403)
        return user

    return _checker


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    module: str,
    detail: str = "",
    request_ip: str = "",
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else 0,
            username=user.username if user else "anonymous",
            action=action,
            module=module,
            detail=detail[:250],
            ip=request_ip,
            created_at=datetime.now().replace(microsecond=0),
        )
    )
    if commit:
        db.commit()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"
