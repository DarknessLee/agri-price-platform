"""元数据接口：字典与按权限过滤的菜单树。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cache
from ..config import CACHE_TTL_DICT
from ..database import get_db
from ..models import Market, Menu, Region, Role, Variety
from ..responses import ok
from ..security import CurrentUser, get_permissions

router = APIRouter(prefix="/meta", tags=["meta"])

REPORT_TYPES = [
    {"key": "daily", "name": "日报"},
    {"key": "weekly", "name": "周报"},
    {"key": "monthly", "name": "月报"},
]
MARKET_TYPES = ["批发", "零售", "产地"]
ALERT_LEVELS = ["高", "中", "低"]


@router.get("/dicts")
def dicts(response: Response, user: CurrentUser, db: Session = Depends(get_db)):
    """基础字典（与用户权限无关，可缓存）。"""
    cache_key = cache.make_key("meta", "dicts")
    cached = cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return ok(cached)

    varieties = db.execute(select(Variety).order_by(Variety.sort, Variety.id)).scalars().all()
    regions = db.execute(select(Region).order_by(Region.sort, Region.id)).scalars().all()
    markets = db.execute(select(Market).order_by(Market.region_code, Market.id)).scalars().all()
    roles = db.execute(select(Role)).scalars().all()
    region_code_set = {r.code for r in regions}
    payload = {
        "varieties": [
            {"id": v.id, "code": v.code, "name": v.name, "category": v.category, "unit": v.unit}
            for v in varieties if v.enabled
        ],
        "regions": [
            {"id": r.id, "code": r.code, "name": r.name, "level": r.level}
            for r in regions if r.enabled
        ],
        "markets": [
            {
                "id": m.id,
                "code": m.code,
                "name": m.name,
                "region_code": m.region_code if m.region_code in region_code_set else "",
                "market_type": m.market_type,
            }
            for m in markets if m.enabled
        ],
        "market_types": MARKET_TYPES,
        "alert_levels": ALERT_LEVELS,
        "report_types": REPORT_TYPES,
        "roles": [{"key": r.key, "name": r.name} for r in roles],
    }
    cache.set(cache_key, payload, CACHE_TTL_DICT)
    response.headers["X-Cache"] = "MISS"
    return ok(payload)


def _menu_tree(rows: list[Menu], owned: set[str]) -> list[dict]:
    """按权限生成菜单树。

    规则：带权限点的节点必须被角色拥有才可见；不带权限点的节点只有在父节点可见、
    且自身有可见子节点或本身是顶级入口时才可见，避免越权入口以孤立节点形式出现。
    """
    children: dict[str, list[Menu]] = {}
    for m in rows:
        children.setdefault(m.parent_key or "", []).append(m)

    def build(parent_key: str, parent_visible: bool) -> list[dict]:
        result: list[dict] = []
        for m in sorted(children.get(parent_key, []), key=lambda x: (x.sort, x.key)):
            permitted = (not m.permission) or (m.permission in owned)
            if not permitted or not parent_visible:
                continue
            sub = build(m.key, True)
            if children.get(m.key) and not m.permission and not sub:
                # 无权限点的分组节点若子项全部不可见，则整组隐藏
                continue
            result.append({
                "key": m.key,
                "title": m.title,
                "path": m.path,
                "icon": m.icon,
                "permission": m.permission,
                "children": sub,
            })
        return result

    return build("", True)


@router.get("/menus")
def menus(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(select(Menu)).scalars().all()
    owned = set(get_permissions(db, user.role_key))
    return ok(_menu_tree(rows, owned))
