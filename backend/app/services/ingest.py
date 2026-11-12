"""数据导入服务：CSV 解析、逐行校验、按唯一约束去重入库、导入任务与质量问题落库。

流程：
1. 解析 CSV（自动识别 UTF-8 / GBK 编码，兼容中文表头）；
2. 逐行校验品种、地区、市场类型、日期、价格与区间；
3. 已存在的（品种/市场/日期/市场类型）按唯一约束跳过并计数；
4. 写入 price_record、import_task，异常行写入 quality_issue；
5. 同步回写数据源的记录数与最近同步时间。
"""
from __future__ import annotations

import io
import json
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import now
from ..models import DataSource, ImportTask, Market, PriceRecord, QualityIssue, Region, Variety
from ..security import ApiError
from . import quality as quality_service

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_ERROR_ITEMS = 200             # 写入任务的错误明细上限
MAX_ISSUE_ITEMS = 200             # 单次写入质量问题的上限
PRICE_MIN = 0.01
PRICE_MAX = 100000.0

MARKET_TYPES = ("批发", "零售")
REQUIRED_COLUMNS = ("variety", "region", "market_type", "date", "price")
COLUMN_ALIASES = {
    "品种": "variety",
    "品种名称": "variety",
    "地区": "region",
    "省份": "region",
    "市场类型": "market_type",
    "日期": "date",
    "价格": "price",
    "均价": "price",
    "成交量": "volume",
    "交易量": "volume",
    "最低价": "min_price",
    "最高价": "max_price",
}


def template_csv() -> bytes:
    """导入模板：UTF-8 BOM，Excel 直接打开不乱码。"""
    lines = [
        ",".join(("variety", "region", "market_type", "date", "price", "volume", "min_price", "max_price")),
        "生猪,北京,批发,2026-11-01,18.60,1200,18.20,19.00",
        "大白菜,山东,零售,2026-11-01,2.35,860,2.10,2.60",
        "# 说明：variety/region 填品种与地区名称（或编码）；market_type 仅支持 批发、零售；date 格式 YYYY-MM-DD；价格单位元/公斤",
    ]
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def _read_table(content: bytes, filename: str) -> pd.DataFrame:
    """读取 CSV 为字符串 DataFrame，自动尝试常见编码。"""
    if not content:
        raise ApiError("E4001", "上传文件为空")
    if len(content) > MAX_FILE_SIZE:
        raise ApiError("E4002", "文件超过 20MB 上限，请拆分后导入")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(
                io.BytesIO(content),
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:  # 编码不匹配，换下一种
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise ApiError("E4001", "文件内容为空，未读取到表头") from exc
        except pd.errors.ParserError as exc:
            raise ApiError("E4001", "CSV 结构解析失败，请检查分隔符与列数是否一致") from exc
    raise ApiError("E4001", f"无法识别文件编码，{filename} 请另存为 UTF-8 或 GBK 编码的 CSV") from last_error


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """列名去空格、转小写、中文别名映射为英文列名。"""
    mapping: dict[str, str] = {}
    for column in df.columns:
        key = str(column).strip().strip("\ufeff")
        key = COLUMN_ALIASES.get(key, key.lower())
        mapping[column] = key
    return df.rename(columns=mapping)


def _parse_date(value: str) -> date | None:
    """宽松解析日期，失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(value, default: float = 0.0) -> float | None:
    """解析数值；空值返回默认值，非法返回 None。"""
    text = str(value or "").strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return None


def _dim_maps(db: Session) -> tuple[dict, dict, dict]:
    """预载维度：品种（名称/编码）、地区（名称/编码）、市场（地区ID+类型）。"""
    varieties = db.execute(select(Variety)).scalars().all()
    regions = db.execute(select(Region)).scalars().all()
    variety_map: dict[str, Variety] = {}
    for variety in varieties:
        variety_map[variety.name] = variety
        variety_map[variety.code] = variety
    region_map: dict[str, Region] = {}
    for region in regions:
        region_map[region.name] = region
        region_map[region.code] = region
    region_by_id = {region.id: region for region in regions}
    region_by_code = {region.code: region for region in regions}
    markets: dict[tuple[int, str], Market] = {}
    for market in db.execute(select(Market).order_by(Market.id)).scalars().all():
        region = region_by_code.get(market.region_code)
        if region is not None:
            markets.setdefault((region.id, market.market_type), market)
    return variety_map, region_map, markets


def import_prices(
    db: Session,
    *,
    content: bytes,
    filename: str,
    source_id: int,
    username: str,
) -> dict:
    """执行 CSV 导入，返回导入结果（契约 §10 POST /api/data/import）。"""
    source = db.get(DataSource, int(source_id or 0))
    if not source:
        raise ApiError("E4040", "数据源不存在", 404)

    df = _normalize_columns(_read_table(content, filename))
    missing = [name for name in REQUIRED_COLUMNS if name not in df.columns]
    if missing:
        raise ApiError("E4001", f"缺少必需列：{'、'.join(missing)}")
    if len(df) == 0:
        raise ApiError("E4001", "文件没有数据行")

    variety_map, region_map, markets = _dim_maps(db)
    rows_total = int(len(df))
    errors: list[dict] = []
    issue_queue: list[tuple[int, int, date, str]] = []  # (品种ID, 地区ID, 日期, 详情)
    candidates: list[dict] = []
    seen: set[tuple[int, int, date, str]] = set()
    skipped = 0

    def _fail(row_no: int, message: str) -> None:
        if len(errors) < MAX_ERROR_ITEMS:
            errors.append({"row": row_no, "message": message})

    for offset, (_, row) in enumerate(df.iterrows()):
        row_no = offset + 2  # 表头占第 1 行
        variety_name = str(row.get("variety", "")).strip()
        region_name = str(row.get("region", "")).strip()
        market_type = str(row.get("market_type", "")).strip() or "批发"
        date_text = str(row.get("date", "")).strip()

        variety = variety_map.get(variety_name)
        region = region_map.get(region_name)
        price_date = _parse_date(date_text)
        price = _parse_float(row.get("price"), default=None)
        min_price = _parse_float(row.get("min_price"), default=0.0)
        max_price = _parse_float(row.get("max_price"), default=0.0)
        volume = _parse_float(row.get("volume"), default=0.0)

        message = ""
        if not variety:
            message = f"品种「{variety_name}」不存在"
        elif not region:
            message = f"地区「{region_name}」不存在"
        elif market_type not in MARKET_TYPES:
            message = f"市场类型「{market_type}」不支持，仅支持批发、零售"
        elif not price_date:
            message = f"日期「{date_text}」格式不正确，应为 YYYY-MM-DD"
        elif price is None:
            message = "价格不是有效数值"
        elif not (PRICE_MIN <= price <= PRICE_MAX):
            message = f"价格 {price} 超出合理范围（{PRICE_MIN}～{PRICE_MAX}）"
        elif min_price is None or max_price is None or volume is None:
            message = "成交量、最低价、最高价必须为数值"
        elif volume < 0:
            message = "成交量不能为负数"
        elif min_price < 0 or max_price < 0:
            message = "最低价、最高价不能为负数"
        elif min_price and max_price and min_price > max_price:
            message = "最低价不能高于最高价"
        elif min_price and max_price and not (min_price <= price <= max_price):
            message = "价格应介于最低价与最高价之间"

        market = markets.get((region.id, market_type)) if region else None
        if not message and not market:
            message = f"地区「{region_name}」暂无{market_type}市场，无法匹配市场"

        if message:
            _fail(row_no, message)
            if variety and region and price_date and len(issue_queue) < MAX_ISSUE_ITEMS:
                issue_queue.append(
                    (variety.id, region.id, price_date, f"第{row_no}行：{message}")
                )
            continue

        key = (variety.id, market.id, price_date, market_type)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        candidates.append(
            {
                "variety_id": variety.id,
                "region_id": region.id,
                "market_id": market.id,
                "market_type": market_type,
                "price_date": price_date,
                "price": round(price, 2),
                "min_price": round(min_price or price, 2),
                "max_price": round(max_price or price, 2),
                "volume": round(volume, 2),
                "unit": variety.unit or "元/公斤",
            }
        )

    # 查询库中已存在的唯一键，重复行跳过并计数
    rows_ok = 0
    if candidates:
        dates = [item["price_date"] for item in candidates]
        variety_ids = {item["variety_id"] for item in candidates}
        existing_rows = db.execute(
            select(
                PriceRecord.variety_id,
                PriceRecord.market_id,
                PriceRecord.price_date,
                PriceRecord.market_type,
            ).where(
                PriceRecord.price_date >= min(dates),
                PriceRecord.price_date <= max(dates),
                PriceRecord.variety_id.in_(variety_ids),
            )
        ).all()
        existing = {
            (int(row[0]), int(row[1]), row[2], row[3]) for row in existing_rows
        }
        for item in candidates:
            key = (
                item["variety_id"],
                item["market_id"],
                item["price_date"],
                item["market_type"],
            )
            if key in existing:
                skipped += 1
                continue
            db.add(PriceRecord(source_id=source.id, quality_flag="正常", **item))
            existing.add(key)
            rows_ok += 1

    for variety_id, region_id, issue_date, detail in issue_queue:
        quality_service.record_issue(
            db,
            variety_id=variety_id,
            region_id=region_id,
            issue_date=issue_date,
            issue_type="格式错误",
            detail=detail,
        )

    rows_error = rows_total - rows_ok - skipped
    if rows_total and not rows_error and not rows_ok and skipped:
        # 全部为库内已存在的数据：幂等跳过视为成功
        status, status_code = "已完成", "success"
    elif rows_ok and not rows_error:
        status, status_code = "已完成", "success"
    elif rows_ok:
        status, status_code = "部分成功", "partial"
    else:
        status, status_code = "失败", "failed"

    task = ImportTask(
        source_id=source.id,
        filename=(filename or "")[:250],
        rows_total=rows_total,
        rows_ok=rows_ok,
        rows_error=max(rows_error, 0),
        status=status,
        errors=json.dumps(errors, ensure_ascii=False),
        created_by=username,
        created_at=now(),
    )
    db.add(task)

    # 回写数据源统计
    source.last_sync_at = now()
    source.record_count = int(
        db.execute(
            select(func.count(PriceRecord.id)).where(PriceRecord.source_id == source.id)
        ).scalar()
        or 0
    )
    db.commit()
    db.refresh(task)

    return {
        "task_id": task.id,
        "filename": task.filename,
        "source": source.name,
        "rows_total": rows_total,
        "rows_ok": rows_ok,
        "rows_error": task.rows_error,
        "rows_skipped": skipped,
        "status": status,
        "status_code": status_code,
        "errors": errors,
        "truncated": len(errors) >= MAX_ERROR_ITEMS,
    }
