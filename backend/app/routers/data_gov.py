"""数据治理接口（契约 §10）：数据源管理、数据质量、CSV 导入与导入任务。"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache
from ..database import get_db, now
from ..models import DataSource, ImportTask, PriceRecord, QualityIssue
from ..responses import ok, page_args, paged
from ..security import ApiError, CurrentUser, client_ip, require_permission, write_audit
from ..services import ingest, quality

router = APIRouter(tags=["数据治理"])

ISSUE_STATUS = ("待处理", "已处理", "已排除")
RESOLVE_ACTIONS = {"fix": "已处理", "exclude": "已排除"}


class SourceCreate(BaseModel):
    name: str
    type: str = "平台接口"
    protocol: str = "REST"
    owner: str = ""
    description: str = ""


class SourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    protocol: str | None = None
    owner: str | None = None
    status: str | None = None
    description: str | None = None


class ResolveBody(BaseModel):
    action: str = "fix"


def _fmt_time(value) -> str | None:
    """时间 -> YYYY-MM-DDTHH:MM:SS。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _source_item(source: DataSource, record_count: int) -> dict:
    """数据源 -> 契约结构。"""
    return {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "protocol": source.protocol,
        "owner": source.owner,
        "status": source.status,
        "last_sync_at": _fmt_time(source.last_sync_at),
        "record_count": int(record_count),
        "description": source.description,
    }


def _get_source(db: Session, source_id: int) -> DataSource:
    """按主键取数据源。"""
    source = db.get(DataSource, int(source_id or 0))
    if not source:
        raise ApiError("E4040", "数据源不存在", 404)
    return source


# --------------------------------------------------------------------------- #
# 数据源
# --------------------------------------------------------------------------- #

@router.get("/sources")
def list_sources(
    _perm: object = Depends(require_permission("data:view")),
    db: Session = Depends(get_db),
):
    """数据源列表（含实际记录数与最近同步时间）。"""
    sources = db.execute(select(DataSource).order_by(DataSource.id)).scalars().all()
    counts = {
        int(row[0]): int(row[1])
        for row in db.execute(
            select(PriceRecord.source_id, func.count(PriceRecord.id)).group_by(
                PriceRecord.source_id
            )
        ).all()
    }
    return ok([_source_item(source, counts.get(source.id, 0)) for source in sources])


@router.post("/sources")
def create_source(
    body: SourceCreate,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("data:source")),
    db: Session = Depends(get_db),
):
    """新增数据源。"""
    name = (body.name or "").strip()
    if not name:
        raise ApiError("E4001", "数据源名称不能为空")
    exists = db.execute(select(DataSource).where(DataSource.name == name)).scalar_one_or_none()
    if exists:
        raise ApiError("E4090", "数据源名称已存在", 409)
    source = DataSource(
        name=name[:128],
        type=(body.type or "平台接口")[:32],
        protocol=(body.protocol or "REST")[:64],
        owner=(body.owner or "")[:64],
        description=(body.description or "")[:255],
        status="正常",
        record_count=0,
        created_at=now(),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    write_audit(
        db, user, "新增", "数据治理", f"新增数据源 {source.name}", client_ip(request)
    )
    return ok(_source_item(source, 0))


@router.put("/sources/{source_id}")
def update_source(
    source_id: int,
    body: SourceUpdate,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("data:source")),
    db: Session = Depends(get_db),
):
    """编辑数据源（部分字段）。"""
    source = _get_source(db, source_id)
    payload = body.model_dump(exclude_unset=True)
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            raise ApiError("E4001", "数据源名称不能为空")
        duplicate = db.execute(
            select(DataSource).where(DataSource.name == name, DataSource.id != source.id)
        ).scalar_one_or_none()
        if duplicate:
            raise ApiError("E4090", "数据源名称已存在", 409)
        source.name = name[:128]
    for field, limit in (("type", 32), ("protocol", 64), ("owner", 64), ("status", 16), ("description", 255)):
        if field in payload and payload[field] is not None:
            setattr(source, field, str(payload[field])[:limit])
    db.commit()
    db.refresh(source)
    count = int(
        db.execute(
            select(func.count(PriceRecord.id)).where(PriceRecord.source_id == source.id)
        ).scalar()
        or 0
    )
    write_audit(
        db, user, "编辑", "数据治理", f"编辑数据源 {source.name}", client_ip(request)
    )
    return ok(_source_item(source, count))


@router.post("/sources/{source_id}/sync")
def sync_source(
    source_id: int,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("data:source")),
    db: Session = Depends(get_db),
):
    """同步数据源：刷新记录数与最近同步时间。"""
    source = _get_source(db, source_id)
    count = int(
        db.execute(
            select(func.count(PriceRecord.id)).where(PriceRecord.source_id == source.id)
        ).scalar()
        or 0
    )
    source.record_count = count
    source.last_sync_at = now()
    if source.status != "停用":
        source.status = "正常"
    db.commit()
    db.refresh(source)
    cache.invalidate("dashboard", "prices", "meta")
    write_audit(
        db, user, "同步", "数据治理", f"同步数据源 {source.name}，共 {count} 条记录", client_ip(request)
    )
    return ok(
        {
            "ok": True,
            "synced": count,
            "status": source.status,
            "last_sync_at": _fmt_time(source.last_sync_at),
        }
    )


# --------------------------------------------------------------------------- #
# 数据质量
# --------------------------------------------------------------------------- #

@router.get("/quality/summary")
def quality_summary(
    _perm: object = Depends(require_permission("data:view")),
    db: Session = Depends(get_db),
):
    """数据质量汇总。"""
    return ok(quality.summary(db))


@router.get("/quality/issues")
def quality_issues(
    type: str | None = Query(default=None, description="问题类型"),
    status: str | None = Query(default=None, description="处理状态"),
    variety_id: int | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _perm: object = Depends(require_permission("data:view")),
    db: Session = Depends(get_db),
):
    """质量问题分页列表。"""
    page, page_size = page_args(page, page_size)
    conds = []
    if type:
        conds.append(QualityIssue.issue_type.in_(quality.types_for(type)))
    if status:
        if status not in ISSUE_STATUS:
            raise ApiError("E4001", "处理状态仅支持待处理、已处理、已排除")
        conds.append(QualityIssue.status == status)
    if variety_id:
        conds.append(QualityIssue.variety_id == int(variety_id))
    start_date, end_date = None, None
    if start or end:
        start_date = quality.parse_date(start, "开始日期")
        end_date = quality.parse_date(end, "结束日期")
    if start_date:
        conds.append(QualityIssue.issue_date >= start_date)
    if end_date:
        conds.append(QualityIssue.issue_date <= end_date)

    total = int(
        db.execute(select(func.count(QualityIssue.id)).where(*conds)).scalar() or 0
    )
    issues = (
        db.execute(
            select(QualityIssue)
            .where(*conds)
            .order_by(QualityIssue.issue_date.desc(), QualityIssue.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return paged(quality.issue_rows(db, list(issues)), total, page, page_size)


@router.post("/quality/issues/{issue_id}/resolve")
def resolve_issue(
    issue_id: int,
    body: ResolveBody,
    request: Request,
    user: CurrentUser,
    _perm: object = Depends(require_permission("data:import")),
    db: Session = Depends(get_db),
):
    """标记质量问题（修正/排除）。"""
    issue = db.get(QualityIssue, int(issue_id or 0))
    if not issue:
        raise ApiError("E4040", "质量问题不存在", 404)
    action = (body.action or "").strip().lower()
    if action not in RESOLVE_ACTIONS:
        raise ApiError("E4001", "处理动作仅支持 fix、exclude")
    issue.status = RESOLVE_ACTIONS[action]
    issue.resolved_by = user.display_name or user.username
    issue.resolved_at = now()
    db.commit()
    write_audit(
        db,
        user,
        "处理",
        "数据治理",
        f"处理质量问题#{issue.id}（{issue.issue_type}）：{issue.status}",
        client_ip(request),
    )
    return ok({"ok": True, "status": issue.status})


@router.get("/quality/template")
def quality_template(
    _perm: object = Depends(require_permission("data:view")),
):
    """下载价格数据导入模板（CSV）。"""
    filename = "价格数据导入模板.csv"
    headers = {
        "Content-Disposition": (
            "attachment; filename=price_import_template.csv; "
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Access-Control-Expose-Headers": "Content-Disposition",
    }
    return Response(
        content=ingest.template_csv(), media_type="text/csv; charset=utf-8", headers=headers
    )


# --------------------------------------------------------------------------- #
# 数据导入
# --------------------------------------------------------------------------- #

@router.post("/data/import")
async def import_data(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(..., description="CSV 文件"),
    source_id: int = Form(default=1, description="数据源ID"),
    _perm: object = Depends(require_permission("data:import")),
    db: Session = Depends(get_db),
):
    """上传 CSV 并导入价格数据。"""
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith((".csv", ".txt")):
        raise ApiError("E4001", "仅支持 CSV 格式文件")
    content = await file.read()
    result = ingest.import_prices(
        db,
        content=content,
        filename=filename,
        source_id=source_id,
        username=user.display_name or user.username,
    )
    cache.invalidate("dashboard", "prices", "meta")
    write_audit(
        db,
        user,
        "导入",
        "数据治理",
        f"导入 {filename}：成功 {result['rows_ok']} 条，失败 {result['rows_error']} 条，跳过 {result['rows_skipped']} 条",
        client_ip(request),
    )
    return ok(result)


@router.get("/data/import-tasks")
def list_import_tasks(
    source_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    _perm: object = Depends(require_permission("data:view")),
    db: Session = Depends(get_db),
):
    """导入任务分页列表。"""
    page, page_size = page_args(page, page_size)
    conds = []
    if source_id:
        conds.append(ImportTask.source_id == int(source_id))
    total = int(
        db.execute(select(func.count(ImportTask.id)).where(*conds)).scalar() or 0
    )
    rows = db.execute(
        select(ImportTask, DataSource.name)
        .outerjoin(DataSource, DataSource.id == ImportTask.source_id)
        .where(*conds)
        .order_by(ImportTask.created_at.desc(), ImportTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            "id": task.id,
            "source": source_name or "",
            "filename": task.filename,
            "rows_total": task.rows_total,
            "rows_ok": task.rows_ok,
            "rows_error": task.rows_error,
            "status": task.status,
            "created_by": task.created_by,
            "created_at": _fmt_time(task.created_at),
        }
        for task, source_name in rows
    ]
    return paged(items, total, page, page_size)
