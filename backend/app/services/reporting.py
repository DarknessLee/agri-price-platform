"""报告服务：日报 / 周报 / 月报生成、查询与导出（契约 §9 / M3 §5）。

generate_report(db, user, report_type="daily", date=None, period_start=None, period_end=None,
                variety_ids=None, region_ids=None, commit=True) -> Report

报告内容为结构化 JSON（sections: [{title, paragraphs, table:{columns, rows}}]），
并渲染为 HTML 与 Markdown 一并存入 Report.metrics（Report 表无 content 字段）；
报告正文写入对象存储，Report.file_path 保存对象键（reports/report_{id}_{type}.html），
MinIO 不可用时 storage 自动落本地 .runtime/storage 同键路径；历史绝对路径文件仍兼容读取。
"""
from __future__ import annotations

import html as html_lib
import io
import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import storage
from ..database import now
from ..models import AlertRecord, ForecastResult, ModelVersion, PriceRecord, Region, Report, Variety
from ..security import ApiError
from . import notification

logger = logging.getLogger(__name__)

REPORT_TYPES: dict[str, str] = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
DEFAULT_MARKET_TYPE = "批发"


# ============================ 工具 ============================

def _read_json(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (ValueError, TypeError):
        return default
    return value if value is not None else default


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ApiError("E4001", "日期格式不正确，应为 YYYY-MM-DD", 400)


def _int_list(value: Any) -> list[int]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [item for item in value.replace("，", ",").split(",") if item.strip()]
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        raise ApiError("E4001", "品种/地区参数格式不正确", 400)


def _is_object_key(value: Any) -> bool:
    """file_path 是否为对象键；历史数据保存的是本地绝对路径。"""
    text = str(value or "")
    return text.startswith(("reports/", "models/", "imports/"))


def _stored_html(record: Report) -> str:
    """从对象存储读取报告正文；历史本地文件路径作为兼容回退。"""
    key = str(record.file_path or "")
    if key:
        if _is_object_key(key):
            content = storage.get_text(key)
            if content:
                return content
        else:
            try:
                from pathlib import Path

                path = Path(key)
                if path.is_file():
                    return path.read_text(encoding="utf-8")
            except OSError:
                pass
    # 旧数据 file_path 为空时按约定对象键推导，保证迁移后仍可下载
    if record.id:
        content = storage.get_text(storage.report_key(record.id, record.report_type))
        if content:
            return content
    return ""


def _period_of(report_type: str, date_arg: Any, period_start: Any, period_end: Any) -> tuple[date, date]:
    if report_type not in REPORT_TYPES:
        raise ApiError("E4001", "报告类型仅支持 daily/weekly/monthly", 400)
    anchor = _to_date(date_arg) or date.today()
    start = _to_date(period_start)
    end = _to_date(period_end)
    if start and end:
        if end < start:
            raise ApiError("E4001", "报告结束日期不能早于开始日期", 400)
        return start, end
    if start and not end:
        return start, start + timedelta(days=6 if report_type == "weekly" else 0)
    if end and not start:
        days = 6 if report_type == "weekly" else 0
        return end - timedelta(days=days), end
    if report_type == "daily":
        return anchor, anchor
    if report_type == "weekly":
        return anchor - timedelta(days=6), anchor
    return anchor.replace(day=1), anchor


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _pct(current: float, previous: float) -> float:
    if not previous:
        return 0.0
    return round((current / previous - 1.0) * 100.0, 2)


def _table(columns: list[str], rows: list[list[Any]]) -> dict:
    return {"columns": columns, "rows": rows}


def _load_prices(db: Session, start: date, end: date) -> list[tuple[int, int, date, float]]:
    rows = db.execute(
        select(PriceRecord.variety_id, PriceRecord.region_id, PriceRecord.price_date, PriceRecord.price)
        .where(PriceRecord.market_type == DEFAULT_MARKET_TYPE)
        .where(PriceRecord.price_date >= start)
        .where(PriceRecord.price_date <= end)
    ).all()
    if not rows:
        rows = db.execute(
            select(PriceRecord.variety_id, PriceRecord.region_id, PriceRecord.price_date, PriceRecord.price)
            .where(PriceRecord.price_date >= start)
            .where(PriceRecord.price_date <= end)
        ).all()
    return [
        (int(v), int(r), d, float(p))
        for v, r, d, p in rows
        if p is not None
    ]


def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    varieties = {int(v.id): v.name for v in db.execute(select(Variety)).scalars().all()}
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    return varieties, regions


# ============================ 报告内容 ============================

def _build_sections(
    db: Session,
    start: date,
    end: date,
    variety_ids: list[int],
    region_ids: list[int],
) -> tuple[list[dict], dict, str]:
    varieties, regions = _name_maps(db)
    span_days = (end - start).days + 1
    prev_start = start - timedelta(days=span_days)
    prev_end = start - timedelta(days=1)
    rows = _load_prices(db, start, end)
    prev_rows = _load_prices(db, prev_start, prev_end)
    if variety_ids:
        allowed = set(variety_ids)
        rows = [row for row in rows if row[0] in allowed]
        prev_rows = [row for row in prev_rows if row[0] in allowed]
    if region_ids:
        allowed_regions = set(region_ids)
        rows = [row for row in rows if row[1] in allowed_regions]
        prev_rows = [row for row in prev_rows if row[1] in allowed_regions]

    # 按品种汇总
    by_variety: dict[int, list[float]] = {}
    for variety_id, _region_id, _day, price in rows:
        by_variety.setdefault(variety_id, []).append(price)
    prev_by_variety: dict[int, list[float]] = {}
    for variety_id, _region_id, _day, price in prev_rows:
        prev_by_variety.setdefault(variety_id, []).append(price)

    variety_table_rows: list[list[Any]] = []
    movers: list[tuple[str, float, float]] = []
    all_prices: list[float] = []
    for variety_id, values in sorted(by_variety.items()):
        avg = _avg(values)
        all_prices.extend(values)
        change = _pct(avg, _avg(prev_by_variety.get(variety_id, [])))
        variety_table_rows.append(
            [
                varieties.get(variety_id, ""),
                avg,
                change,
                round(max(values), 2),
                round(min(values), 2),
                len(values),
            ]
        )
        movers.append((varieties.get(variety_id, ""), avg, change))
    movers.sort(key=lambda item: abs(item[2]), reverse=True)

    overall_avg = _avg(all_prices)
    prev_overall = _avg([price for _v, _r, _d, price in prev_rows])
    overall_change = _pct(overall_avg, prev_overall)
    date_count = len({day for _v, _r, day, _p in rows})

    sections: list[dict] = []
    overview_paragraphs = [
        f"本报告统计区间为 {start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}，"
        f"共覆盖 {len(by_variety)} 个品种、{len({region for _v, region, _d, _p in rows})} 个地区、"
        f"{date_count} 个价格日期、{len(rows)} 条批发价格记录。",
        f"区间内批发价总体均值 {overall_avg:.2f} 元/公斤，较上一周期（{prev_start.strftime('%Y-%m-%d')} 至 "
        f"{prev_end.strftime('%Y-%m-%d')}）{'上涨' if overall_change > 0 else '下跌' if overall_change < 0 else '持平'}"
        f" {abs(overall_change):.2f}%。",
    ]
    if movers:
        top = movers[0]
        overview_paragraphs.append(
            f"波动最大的品种为{top[0]}，均价 {top[1]:.2f} 元/公斤，周期内变化 {top[2]:+.2f}%。"
        )
    sections.append(
        {
            "title": "一、市场总体概况",
            "paragraphs": overview_paragraphs,
            "table": _table(
                ["品种", "均价(元/公斤)", "环比变化(%)", "最高价", "最低价", "记录数"],
                variety_table_rows,
            ),
        }
    )

    focus_rows = [
        [name, avg, change] for name, avg, change in movers[:5]
    ]
    sections.append(
        {
            "title": "二、重点品种价格",
            "paragraphs": [
                "按周期内价格变化幅度排序，前五位品种如下，建议重点关注其供需与库存变化。"
                if focus_rows
                else "统计区间内暂无价格数据。"
            ],
            "table": _table(["品种", "均价(元/公斤)", "周期变化(%)"], focus_rows),
        }
    )

    # 区域价差
    by_variety_region: dict[tuple[int, int], list[float]] = {}
    for variety_id, region_id, _day, price in rows:
        by_variety_region.setdefault((variety_id, region_id), []).append(price)
    spread_map: dict[int, dict[int, float]] = {}
    for (variety_id, region_id), values in by_variety_region.items():
        spread_map.setdefault(variety_id, {})[region_id] = _avg(values)
    spread_rows: list[list[Any]] = []
    for variety_id, region_avg in sorted(spread_map.items()):
        if len(region_avg) < 2:
            continue
        high_region = max(region_avg, key=lambda rid: region_avg[rid])
        low_region = min(region_avg, key=lambda rid: region_avg[rid])
        spread = round(region_avg[high_region] - region_avg[low_region], 2)
        spread_pct = round(spread / region_avg[low_region] * 100.0, 2) if region_avg[low_region] else 0.0
        spread_rows.append(
            [
                varieties.get(variety_id, ""),
                regions.get(high_region, ""),
                round(region_avg[high_region], 2),
                regions.get(low_region, ""),
                round(region_avg[low_region], 2),
                spread,
                spread_pct,
            ]
        )
    spread_rows.sort(key=lambda item: item[6], reverse=True)
    sections.append(
        {
            "title": "三、区域价差",
            "paragraphs": [
                "区域价差反映跨区调运套利空间，价差率超过 10% 时建议核查物流成本与区域供需。"
                if spread_rows
                else "统计区间内暂无可比区域价格。"
            ],
            "table": _table(
                ["品种", "最高价地区", "最高价", "最低价地区", "最低价", "价差", "价差率(%)"],
                spread_rows,
            ),
        }
    )

    # 预警情况
    alert_rows = db.execute(
        select(AlertRecord)
        .where(AlertRecord.alert_date >= start)
        .where(AlertRecord.alert_date <= end)
        .order_by(AlertRecord.alert_date.desc(), AlertRecord.id.desc())
        .limit(10)
    ).scalars().all()
    alert_total = int(
        db.execute(
            select(func.count(AlertRecord.id))
            .where(AlertRecord.alert_date >= start)
            .where(AlertRecord.alert_date <= end)
        ).scalar()
        or 0
    )
    level_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for record in db.execute(
        select(AlertRecord)
        .where(AlertRecord.alert_date >= start)
        .where(AlertRecord.alert_date <= end)
    ).scalars().all():
        level_counts[record.level] = level_counts.get(record.level, 0) + 1
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
    level_text = "、".join(f"{level} {count} 条" for level, count in level_counts.items()) or "无"
    sections.append(
        {
            "title": "四、预警情况",
            "paragraphs": [
                f"统计区间内共产生预警 {alert_total} 条（{level_text}）；"
                f"其中待处理 {status_counts.get('待处理', 0)} 条、处理中 {status_counts.get('处理中', 0)} 条、"
                f"已关闭 {status_counts.get('已关闭', 0)} 条。"
            ],
            "table": _table(
                ["预警日期", "级别", "标题", "状态"],
                [
                    [
                        record.alert_date.strftime("%Y-%m-%d") if record.alert_date else "",
                        record.level,
                        record.title,
                        record.status,
                    ]
                    for record in alert_rows
                ],
            ),
        }
    )

    # 预测摘要
    active_models = db.execute(
        select(ModelVersion).where(ModelVersion.is_active.is_(True))
    ).scalars().all()
    if variety_ids:
        active_models = [m for m in active_models if int(m.variety_id) in set(variety_ids)]
    avg_mape = _avg([float(m.mape or 0) for m in active_models])
    avg_dir = _avg([float(m.direction_acc or 0) for m in active_models])
    forecast_rows = db.execute(
        select(ForecastResult).order_by(ForecastResult.id.desc()).limit(10)
    ).scalars().all()
    forecast_table: list[list[Any]] = []
    for row in forecast_rows:
        forecast_table.append(
            [
                varieties.get(int(row.variety_id), ""),
                regions.get(int(row.region_id), ""),
                row.target_date.strftime("%Y-%m-%d") if row.target_date else "",
                round(float(row.point or 0), 2),
                row.direction,
                round(float(row.expected_change_pct or 0), 2),
            ]
        )
    sections.append(
        {
            "title": "五、预测摘要",
            "paragraphs": [
                f"当前在线预测模型 {len(active_models)} 个，平均回测 MAPE {avg_mape:.2f}%、"
                f"平均方向准确率 {avg_dir:.2f}%。最近预测结果如下。"
                if active_models
                else "当前暂无在线预测模型，预测摘要将在模型训练后自动补充。"
            ],
            "table": _table(["品种", "地区", "预测日期", "预测价", "方向", "预期涨跌(%)"], forecast_table),
        }
    )

    # 结论与建议
    advice: list[str] = []
    if overall_change > 2:
        advice.append("整体价格上行，建议关注供给端变化，提前锁定采购与库存成本。")
    elif overall_change < -2:
        advice.append("整体价格下行，建议控制库存规模，防范跌价风险。")
    else:
        advice.append("整体价格平稳，建议维持常规采购与销售节奏。")
    if movers:
        advice.append(f"重点关注{movers[0][0]}的价格波动（{movers[0][2]:+.2f}%），及时核实主产区供需信息。")
    if spread_rows:
        advice.append(f"区域价差最大的是{spread_rows[0][0]}（价差率 {spread_rows[0][6]:.2f}%），可结合调运成本开展跨区购销。")
    if alert_total:
        advice.append(f"本期共有 {alert_total} 条预警，建议及时处置未关闭预警并复盘规则命中情况。")
    sections.append(
        {
            "title": "六、结论与建议",
            "paragraphs": advice,
            "table": _table(["指标", "数值"], [
                ["区间均价(元/公斤)", overall_avg],
                ["区间价格变化(%)", overall_change],
                ["预警条数", alert_total],
                ["在线模型数", len(active_models)],
                ["平均回测MAPE(%)", avg_mape],
                ["平均方向准确率(%)", avg_dir],
            ]),
        }
    )

    stats = {
        "avg_price": overall_avg,
        "price_change_pct": overall_change,
        "variety_count": len(by_variety),
        "region_count": len({region for _v, region, _d, _p in rows}),
        "record_count": len(rows),
        "alert_count": alert_total,
        "model_count": len(active_models),
        "avg_mape": avg_mape,
        "avg_direction_acc": avg_dir,
    }
    summary_text = (
        f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}，农产品批发价区间均值 {overall_avg:.2f} 元/公斤，"
        f"较上一周期{'上涨' if overall_change > 0 else '下跌' if overall_change < 0 else '持平'} {abs(overall_change):.2f}%，"
        f"共产生预警 {alert_total} 条。"
    )
    return sections, stats, summary_text


def _render_html(title: str, summary: str, sections: list[dict], meta: dict) -> str:
    def esc(value: Any) -> str:
        return html_lib.escape(str(value if value is not None else ""))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        f"<title>{esc(title)}</title>",
        "<style>body{font-family:'Microsoft YaHei',Arial,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#222;line-height:1.7}"
        "h1{font-size:22px;border-bottom:2px solid #2f6f4f;padding-bottom:8px}"
        "h2{font-size:17px;margin-top:24px;color:#2f6f4f}"
        "p{margin:8px 0}table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}"
        "th,td{border:1px solid #d5ddd8;padding:6px 8px;text-align:left}th{background:#eef5f0}"
        ".meta{color:#666;font-size:13px}</style></head><body>",
        f"<h1>{esc(title)}</h1>",
        f'<p class="meta">报告类型：{esc(meta.get("report_type_name", ""))}　统计区间：'
        f'{esc(meta.get("period_start", ""))} 至 {esc(meta.get("period_end", ""))}　生成时间：{esc(meta.get("created_at", ""))}</p>',
        f"<p><strong>摘要：</strong>{esc(summary)}</p>",
    ]
    for section in sections:
        parts.append(f"<h2>{esc(section.get('title', ''))}</h2>")
        for paragraph in section.get("paragraphs", []) or []:
            parts.append(f"<p>{esc(paragraph)}</p>")
        table = section.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        if columns:
            parts.append("<table><thead><tr>")
            parts.extend(f"<th>{esc(col)}</th>" for col in columns)
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                parts.extend(f"<td>{esc(cell)}</td>" for cell in row)
                parts.append("</tr>")
            parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "".join(parts)


def _render_markdown(title: str, summary: str, sections: list[dict], meta: dict) -> str:
    lines = [f"# {title}", ""]
    lines.append(
        f"> 报告类型：{meta.get('report_type_name', '')}　统计区间：{meta.get('period_start', '')} 至 "
        f"{meta.get('period_end', '')}　生成时间：{meta.get('created_at', '')}"
    )
    lines.append("")
    lines.append(f"**摘要：** {summary}")
    lines.append("")
    for section in sections:
        lines.append(f"## {section.get('title', '')}")
        lines.append("")
        for paragraph in section.get("paragraphs", []) or []:
            lines.append(str(paragraph))
            lines.append("")
        table = section.get("table") or {}
        columns = table.get("columns") or []
        rows = table.get("rows") or []
        if columns:
            lines.append("| " + " | ".join(str(col) for col in columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            lines.append("")
    return "\n".join(lines)


# ============================ 生成与查询 ============================

def generate_report(
    db: Session,
    user: Any = None,
    report_type: str = "daily",
    date: Any = None,
    period_start: Any = None,
    period_end: Any = None,
    variety_ids: Any = None,
    region_ids: Any = None,
    commit: bool = True,
):
    """生成报告并持久化，返回 Report 记录。"""
    report_type = str(report_type or "daily")
    if report_type not in REPORT_TYPES:
        raise ApiError("E4001", "报告类型仅支持 daily/weekly/monthly", 400)
    start, end = _period_of(report_type, date, period_start, period_end)
    vids = _int_list(variety_ids)
    rids = _int_list(region_ids)

    sections, stats, summary_text = _build_sections(db, start, end, vids, rids)
    created_at_text = now().strftime("%Y-%m-%d %H:%M:%S")
    type_name = REPORT_TYPES[report_type]
    scope = ""
    if vids:
        varieties, _regions = _name_maps(db)
        scope = "·".join(varieties.get(vid, "") for vid in vids[:3])
        if len(vids) > 3:
            scope += "等"
    title = f"{scope}{'农产品' if not scope else ''}价格分析{type_name}（{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}）"
    meta = {
        "report_type": report_type,
        "report_type_name": type_name,
        "period_start": start.strftime("%Y-%m-%d"),
        "period_end": end.strftime("%Y-%m-%d"),
        "created_at": created_at_text,
    }
    content_html = _render_html(title, summary_text, sections, meta)
    content_md = _render_markdown(title, summary_text, sections, meta)
    metrics_payload = {
        "stats": stats,
        "sections": sections,
        "content_html": content_html,
        "content_md": content_md,
        "meta": meta,
    }
    created_by = (
        (getattr(user, "display_name", None) or getattr(user, "username", None)) if user else "system"
    ) or "system"
    record = Report(
        title=title,
        report_type=report_type,
        period_start=start,
        period_end=end,
        variety_ids=",".join(str(v) for v in vids),
        region_ids=",".join(str(r) for r in rids),
        status="已发布",
        summary=summary_text,
        metrics=json.dumps(metrics_payload, ensure_ascii=False),
        file_path="",
        created_by=str(created_by)[:64],
        created_at=now(),
    )
    db.add(record)
    db.flush()

    # 站内通知：报告生成成功。与报告同事务提交，通知失败不得影响报告生成。
    try:
        notification.broadcast(
            db,
            f"报告已生成：{record.title}",
            f"{record.report_type} {start.strftime('%Y-%m-%d')}~{end.strftime('%Y-%m-%d')}",
            category="报告",
            level="低",
            link="/report",
        )
    except Exception:
        logger.exception("报告生成通知发送失败：report_id=%s", record.id)

    # 报告正文写入对象存储，file_path 保存对象键，供下载接口直接读取
    try:
        key = storage.report_key(record.id, report_type)
        storage.put_text(key, content_html, content_type="text/html; charset=utf-8")
        record.file_path = key
        db.add(record)
    except Exception:  # pragma: no cover - 对象存储异常时仍可从 metrics 读取正文
        logger.exception("报告正文写入对象存储失败：report_id=%s", record.id)
        record.file_path = ""

    if commit:
        db.commit()
    else:
        db.flush()
    return record


def _fallback_html(record: Report) -> str:
    """历史数据缺少正文时的兜底 HTML，保证详情与下载不返回空内容。"""
    period = ""
    if record.period_start and record.period_end:
        period = f"{record.period_start.strftime('%Y-%m-%d')} 至 {record.period_end.strftime('%Y-%m-%d')}"
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html_lib.escape(record.title or '')}</title></head><body>"
        f"<h1>{html_lib.escape(record.title or '')}</h1>"
        f"<p>统计区间：{html_lib.escape(period)}</p>"
        f"<p>{html_lib.escape(record.summary or '')}</p>"
        "</body></html>"
    )


def serialize_report(record: Report, include_content: bool = False) -> dict:
    payload = _read_json(record.metrics, {})
    stats = payload.get("stats") or {}
    data = {
        "id": record.id,
        "title": record.title,
        "report_type": record.report_type,
        "report_type_name": REPORT_TYPES.get(record.report_type, record.report_type),
        "period_start": record.period_start.strftime("%Y-%m-%d") if record.period_start else "",
        "period_end": record.period_end.strftime("%Y-%m-%d") if record.period_end else "",
        "status": record.status,
        "summary": record.summary,
        "created_by": record.created_by,
        "created_at": record.created_at.strftime("%Y-%m-%dT%H:%M:%S") if record.created_at else "",
        "metrics": stats,
    }
    if include_content:
        data["content_html"] = (
            payload.get("content_html") or _stored_html(record) or _fallback_html(record)
        )
        data["sections"] = payload.get("sections", [])
        data["variety_ids"] = record.variety_ids
        data["region_ids"] = record.region_ids
    return data


def list_reports(
    db: Session,
    report_type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[dict], int]:
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 10)))
    conditions = []
    if report_type:
        if str(report_type) not in REPORT_TYPES:
            raise ApiError("E4001", "报告类型仅支持 daily/weekly/monthly", 400)
        conditions.append(Report.report_type == str(report_type))
    count_stmt = select(func.count(Report.id))
    list_stmt = select(Report).order_by(Report.id.desc())
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar() or 0)
    rows = db.execute(list_stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return [serialize_report(row) for row in rows], total


def get_report(db: Session, report_id: int, include_content: bool = True) -> dict:
    record = db.get(Report, int(report_id))
    if record is None:
        raise ApiError("E4040", "报告不存在", 404)
    return serialize_report(record, include_content=include_content)


def delete_report(db: Session, report_id: int, commit: bool = True) -> None:
    record = db.get(Report, int(report_id))
    if record is None:
        raise ApiError("E4040", "报告不存在", 404)
    file_path = str(record.file_path or "")
    report_id_value = int(record.id)
    report_type = str(record.report_type or "")
    db.delete(record)
    if commit:
        db.commit()
    else:
        db.flush()
    if file_path:
        if _is_object_key(file_path):
            storage.delete(file_path)
        else:
            try:
                from pathlib import Path

                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass
    # localStorage / 旧版数据兼容：对象键由 id+type 约定推导，删除时一并清理
    try:
        storage.delete(storage.report_key(report_id_value, report_type))
    except Exception:  # pragma: no cover - 清理失败不影响删除结果
        logger.exception("报告对象清理失败：report_id=%s", report_id_value)


def report_download(db: Session, report_id: int, fmt: str = "html") -> tuple[str, str]:
    """返回 (文件名, 文本内容)；fmt 支持 html / md。正文优先从对象存储读取。"""
    record = db.get(Report, int(report_id))
    if record is None:
        raise ApiError("E4040", "报告不存在", 404)
    fmt = str(fmt or "html").lower()
    if fmt not in ("html", "md", "markdown"):
        raise ApiError("E4001", "导出格式仅支持 html、md 或 xlsx", 400)
    payload = _read_json(record.metrics, {})
    if fmt == "html":
        content = _stored_html(record) or payload.get("content_html") or ""
        if not content:
            content = _fallback_html(record)
        extension = "html"
    else:
        content = payload.get("content_md") or ""
        extension = "md"
    if not content:
        content = f"# {record.title}\n\n{record.summary}\n"
    filename = f"{record.report_type}_{record.id}_{record.period_end.strftime('%Y%m%d') if record.period_end else 'report'}.{extension}"
    return filename, content


# ============================ Excel 导出（openpyxl） ============================

STATS_LABELS: list[tuple[str, str]] = [
    ("avg_price", "平均批发价（元/公斤）"),
    ("price_change_pct", "区间涨跌幅（%）"),
    ("variety_count", "品种数"),
    ("region_count", "地区数"),
    ("record_count", "价格记录数"),
    ("alert_count", "预警条数"),
    ("model_count", "在用模型数"),
    ("avg_mape", "平均 MAPE（%）"),
    ("avg_direction_acc", "平均方向准确率（%）"),
]

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_builder():
    """延迟导入 openpyxl 与样式对象，避免服务启动即依赖 Excel 组件。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - 环境缺组件时给出可读提示
        raise ApiError("E5000", f"Excel 导出组件不可用：{exc}", 500)
    return Workbook, Alignment, Border, Font, PatternFill, Side, get_column_letter


def _period_text(record: Report) -> str:
    if record.period_start and record.period_end:
        return f"{record.period_start.strftime('%Y-%m-%d')} 至 {record.period_end.strftime('%Y-%m-%d')}"
    return ""


def _build_xlsx(
    title: str,
    report_type_name: str,
    period_text: str,
    status: str,
    summary: str,
    sections: list[dict],
    stats: dict,
    checked_at: str,
) -> bytes:
    """生成三工作表 Excel：概览 / 价格与预测 / 预警摘要。"""
    Workbook, Alignment, Border, Font, PatternFill, Side, get_column_letter = _xlsx_builder()
    thin = Side(style="thin", color="D5DDD8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="2F6F4F")
    title_font = Font(bold=True, size=13, color="2F6F4F")
    wrap_top = Alignment(wrap_text=True, vertical="top")

    def style_header(ws, columns: list[str], row: int = 1) -> None:
        for index, column in enumerate(columns, start=1):
            cell = ws.cell(row=row, column=index, value=column)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def append_table(ws, columns: list[str], rows: list[list[Any]], row: int) -> int:
        style_header(ws, columns, row)
        row += 1
        for values in rows:
            for index, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=index, value=value)
                cell.border = border
                cell.alignment = wrap_top
            row += 1
        return row

    def fit_width(ws, widths: list[int]) -> None:
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width

    def pick_sections(keywords: tuple[str, ...]) -> list[dict]:
        return [
            section
            for section in sections
            if any(keyword in str(section.get("title", "")) for keyword in keywords)
        ]

    wb = Workbook()

    # ---------- 工作表一：概览 ----------
    overview = wb.active
    overview.title = "概览"
    overview["A1"] = "报告标题"
    overview["B1"] = title
    overview["A2"] = "报告类型"
    overview["B2"] = report_type_name
    overview["A3"] = "统计区间"
    overview["B3"] = period_text
    overview["A4"] = "报告状态"
    overview["B4"] = status
    overview["A5"] = "生成时间"
    overview["B5"] = checked_at
    overview["A6"] = "摘要"
    overview["B6"] = summary
    overview.merge_cells("B6:D6")
    for row in range(1, 7):
        overview.cell(row=row, column=1).font = Font(bold=True)
        overview.cell(row=row, column=1).fill = PatternFill("solid", fgColor="EEF5F0")
        overview.cell(row=row, column=1).border = border
        overview.cell(row=row, column=1).alignment = wrap_top
        overview.cell(row=row, column=2).alignment = wrap_top
        overview.cell(row=row, column=2).border = border
    overview["A8"] = "关键指标"
    overview["A8"].font = title_font
    index = 9
    style_header(overview, ["指标", "数值"], index)
    index += 1
    for key, label in STATS_LABELS:
        if key not in stats:
            continue
        overview.cell(row=index, column=1, value=label).border = border
        overview.cell(row=index, column=2, value=stats.get(key)).border = border
        index += 1
    if index == 10:
        overview.cell(row=index, column=1, value="暂无统计数据").border = border
    fit_width(overview, [24, 52, 26, 20])
    overview.freeze_panes = "A2"

    # ---------- 工作表二：价格与预测 ----------
    price_sheet = wb.create_sheet("价格与预测")
    price_sections = pick_sections(("价格", "预测"))
    price_row = 1
    if not price_sections:
        price_row = append_table(
            price_sheet,
            ["品种", "地区", "期间均价", "期间涨跌幅（%）", "预测均价", "预测方向"],
            [["统计区间内暂无价格与预测数据"] + [""] * 5],
            price_row,
        )
    else:
        for section in price_sections:
            price_sheet.cell(row=price_row, column=1, value=section.get("title", "")).font = title_font
            price_row += 1
            for paragraph in section.get("paragraphs", []) or []:
                price_sheet.cell(row=price_row, column=1, value=str(paragraph)).alignment = wrap_top
                price_sheet.merge_cells(start_row=price_row, start_column=1, end_row=price_row, end_column=6)
                price_row += 1
            table = section.get("table") or {}
            columns = [str(item) for item in (table.get("columns") or [])]
            rows = table.get("rows") or []
            if columns:
                price_row = append_table(price_sheet, columns, rows, price_row)
            price_row += 1
    fit_width(price_sheet, [16, 14, 14, 18, 14, 14, 14, 14])
    price_sheet.freeze_panes = "A2"

    # ---------- 工作表三：预警摘要 ----------
    alert_sheet = wb.create_sheet("预警摘要")
    alert_sections = pick_sections(("预警",))
    alert_row = 1
    if not alert_sections:
        alert_row = append_table(
            alert_sheet,
            ["预警日期", "级别", "品种", "地区", "标题", "状态", "处置人"],
            [["统计区间内无预警记录"] + [""] * 6],
            alert_row,
        )
    else:
        for section in alert_sections:
            alert_sheet.cell(row=alert_row, column=1, value=section.get("title", "")).font = title_font
            alert_row += 1
            table = section.get("table") or {}
            columns = [str(item) for item in (table.get("columns") or [])]
            rows = table.get("rows") or []
            if columns:
                alert_row = append_table(alert_sheet, columns, rows, alert_row)
            else:
                for paragraph in section.get("paragraphs", []) or []:
                    alert_sheet.cell(row=alert_row, column=1, value=str(paragraph)).alignment = wrap_top
                    alert_sheet.merge_cells(
                        start_row=alert_row, start_column=1, end_row=alert_row, end_column=7
                    )
                    alert_row += 1
            alert_row += 1
    fit_width(alert_sheet, [14, 10, 14, 14, 30, 12, 12])
    alert_sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def report_xlsx(db: Session, report_id: int) -> tuple[str, bytes]:
    """把报告导出为 Excel（三工作表），返回 (文件名, 二进制内容)。"""
    record = db.get(Report, int(report_id))
    if record is None:
        raise ApiError("E4040", "报告不存在", 404)
    payload = _read_json(record.metrics, {})
    sections = payload.get("sections") or []
    stats = payload.get("stats") or {}
    data = _build_xlsx(
        title=record.title or "",
        report_type_name=REPORT_TYPES.get(record.report_type, record.report_type),
        period_text=_period_text(record),
        status=record.status or "",
        summary=record.summary or "",
        sections=sections if isinstance(sections, list) else [],
        stats=stats if isinstance(stats, dict) else {},
        checked_at=record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else "",
    )
    suffix = record.period_end.strftime("%Y%m%d") if record.period_end else "report"
    filename = f"{REPORT_TYPES.get(record.report_type, record.report_type)}_{suffix}_{record.id}.xlsx"
    return filename, data


def template_xlsx(report_type: str = "daily") -> tuple[str, bytes]:
    """生成空白报告模板 Excel（三工作表，仅表头与说明）。"""
    report_type = str(report_type or "daily")
    if report_type not in REPORT_TYPES:
        raise ApiError("E4001", "报告类型仅支持 daily/weekly/monthly", 400)
    sections = [
        {
            "title": "价格与预测",
            "paragraphs": ["请填写统计区间后，在系统中生成正式报告。"],
            "table": {
                "columns": [
                    "品种",
                    "地区",
                    "期间均价",
                    "期间涨跌幅（%）",
                    "预测均价",
                    "预测方向",
                    "区间下限",
                    "区间上限",
                ],
                "rows": [],
            },
        },
        {
            "title": "预警摘要",
            "paragraphs": [],
            "table": {
                "columns": ["预警日期", "级别", "品种", "地区", "标题", "状态", "处置人"],
                "rows": [],
            },
        },
    ]
    data = _build_xlsx(
        title="农产品价格分析报告模板",
        report_type_name=REPORT_TYPES[report_type],
        period_text="待填写",
        status="模板",
        summary="空白模板：用于线下填报与归档，正式报告请在系统中生成。",
        sections=sections,
        stats={},
        checked_at="",
    )
    return f"{REPORT_TYPES[report_type]}模板.xlsx", data

