"""报告管理路由（契约 §9）：报告列表、生成、详情、下载与删除。"""
from __future__ import annotations

import io
import urllib.parse
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..responses import ok, paged, page_args
from ..security import ApiError, client_ip, require_permission, write_audit
from ..services import reporting

router = APIRouter(tags=["报告管理"])


def _content_disposition(filename: str, ascii_fallback: str) -> str:
    """中文文件名按 RFC5987 编码，同时保留 ASCII 回退名。"""
    quoted = urllib.parse.quote(filename)
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"


def _xlsx_response(filename: str, content: bytes, ascii_fallback: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(content),
        media_type=reporting.XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": _content_disposition(filename, ascii_fallback)},
    )


def _body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("E4001", "请求体格式不正确", 400)
    return body


@router.get("/reports")
def reports_list(
    report_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: Any = Depends(require_permission("report:view")),
    db: Session = Depends(get_db),
):
    """报告分页列表。"""
    page, page_size = page_args(page, page_size)
    items, total = reporting.list_reports(db, report_type, page, page_size)
    return paged(items, total, page, page_size)


@router.post("/reports/generate")
def reports_generate(
    request: Request,
    body: dict | None = Body(default=None),
    user: Any = Depends(require_permission("report:generate")),
    db: Session = Depends(get_db),
):
    """生成日报 / 周报 / 月报。"""
    data = _body_dict(body)
    record = reporting.generate_report(
        db,
        user,
        report_type=str(data.get("report_type") or "daily"),
        date=data.get("date"),
        period_start=data.get("period_start"),
        period_end=data.get("period_end"),
        variety_ids=data.get("variety_ids"),
        region_ids=data.get("region_ids"),
    )
    payload = reporting.serialize_report(record, include_content=True)
    write_audit(
        db,
        user,
        "生成报告",
        "报告管理",
        f"报告ID={record.id} 类型={record.report_type} 标题={record.title}",
        client_ip(request),
    )
    return ok(
        {
            "id": payload["id"],
            "title": payload["title"],
            "report_type": payload["report_type"],
            "status": payload["status"],
            "content_html": payload.get("content_html", ""),
        }
    )


@router.get("/reports/template")
def reports_template(
    report_type: str = Query(default="daily"),
    user: Any = Depends(require_permission("report:view")),
    db: Session = Depends(get_db),
):
    """下载空白报告模板 Excel（概览 / 价格与预测 / 预警摘要）。"""
    filename, content = reporting.template_xlsx(report_type)
    return _xlsx_response(filename, content, "report_template.xlsx")


@router.get("/reports/{report_id}")
def reports_detail(
    report_id: int,
    user: Any = Depends(require_permission("report:view")),
    db: Session = Depends(get_db),
):
    """报告详情（含结构化内容与 HTML）。"""
    return ok(reporting.get_report(db, report_id, include_content=True))


@router.get("/reports/{report_id}/download")
def reports_download(
    report_id: int,
    fmt: str = Query(default="html", alias="format"),
    user: Any = Depends(require_permission("report:view")),
    db: Session = Depends(get_db),
):
    """下载报告（html / md / xlsx）。"""
    fmt = (fmt or "html").lower()
    if fmt in ("xlsx", "excel"):
        filename, content = reporting.report_xlsx(db, report_id)
        return _xlsx_response(filename, content, "report.xlsx")
    filename, content = reporting.report_download(db, report_id, fmt)
    media_type = "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8"
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/reports/{report_id}")
def reports_delete(
    report_id: int,
    request: Request,
    user: Any = Depends(require_permission("report:generate")),
    db: Session = Depends(get_db),
):
    """删除报告。"""
    reporting.delete_report(db, report_id)
    write_audit(db, user, "删除报告", "报告管理", f"报告ID={report_id}", client_ip(request))
    return ok({"id": report_id})
