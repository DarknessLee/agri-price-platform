"""统一响应构造器：所有接口返回 {code, message, data}。"""
from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def paged(items: list, total: int, page: int = 1, page_size: int = 20) -> dict:
    return ok({"list": items, "total": total, "page": page, "page_size": page_size})


def page_args(page: int = 1, page_size: int = 20) -> tuple[int, int]:
    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 20)))
    return page, page_size
