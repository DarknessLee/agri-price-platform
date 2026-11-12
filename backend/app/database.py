"""数据库连接与会话管理（SQLite，预留 PostgreSQL 迁移能力）。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover - 环境相关
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 本机部分 Windows 环境无法创建 SQLite 临时文件（GROUP BY 会报 unable to open database file）
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, class_=Session)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_dict(obj, *, date_fmt: str = "%Y-%m-%d", time_fmt: str = "%Y-%m-%dT%H:%M:%S") -> dict:
    """把 ORM 对象转换为可序列化 dict（日期/时间转字符串，排除密码散列）。"""
    out: dict = {}
    for column in obj.__table__.columns:
        key = column.key
        if key in {"password_hash", "token"}:
            continue
        value = getattr(obj, key)
        if isinstance(value, datetime):
            value = value.strftime(time_fmt)
        elif isinstance(value, date):
            value = value.strftime(date_fmt)
        out[key] = value
    return out


def now() -> datetime:
    return datetime.now().replace(microsecond=0)
