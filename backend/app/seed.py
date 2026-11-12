"""种子数据生成：主数据、三年日频价格、特征、预警、报告、治理与审计。

所有数据由固定随机种子（20261112）可重建；脚本可重复执行：
    python -m app.seed --reset          # 清空业务数据后重建
    python -m app.seed                  # 仅在库为空时初始化（服务启动时调用）
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .config import IS_SQLITE
from .database import Base, SessionLocal, engine
from .models import (
    AlertRecord,
    AlertRule,
    AuditLog,
    DataSource,
    FeatureRecord,
    ImportTask,
    Market,
    Menu,
    Permission,
    PriceRecord,
    QualityIssue,
    Region,
    Report,
    Role,
    RolePermission,
    ScheduledTask,
    User,
    Variety,
)
from .security import hash_password

RNG_SEED = 20261112
START = date(2023, 1, 1)
END = date(2026, 11, 11)
FEATURE_START = date(2024, 1, 1)

NOW = datetime.now().replace(microsecond=0)

VARIETIES = [
    # (code, name, category, base_price, volume_factor)
    ("pig", "生猪", "畜产品", 16.2, 1.6),
    ("egg", "鸡蛋", "畜产品", 9.2, 0.5),
    ("cabbage", "大白菜", "蔬菜", 2.6, 2.5),
    ("apple", "富士苹果", "水果", 6.8, 0.8),
    ("wheat", "小麦", "粮油", 2.85, 1.2),
]

# (code, name, price_factor, market_size)
REGIONS = [
    ("110000", "北京", 1.10, 1.00),
    ("370000", "山东", 0.94, 1.15),
    ("410000", "河南", 0.96, 1.10),
    ("510000", "四川", 1.02, 1.05),
    ("440000", "广东", 1.12, 1.00),
    ("420000", "湖北", 0.99, 1.02),
]

# (code, name, region_code, market_type, price_factor, volume_base)
MARKETS = [
    ("BJ-XFD", "北京新发地农产品批发市场", "110000", "批发", 1.00, 520),
    ("BJ-DYL", "北京大洋路农副产品市场", "110000", "零售", 1.30, 160),
    ("SD-SG", "山东寿光农产品物流园", "370000", "批发", 1.00, 640),
    ("SD-JN", "山东济南七里堡蔬菜市场", "370000", "零售", 1.28, 180),
    ("HN-WB", "河南万邦国际农产品批发市场", "410000", "批发", 1.00, 580),
    ("HN-ZZ", "河南郑州花园口农贸市场", "410000", "零售", 1.27, 150),
    ("SC-MY", "四川濛阳农副产品综合批发市场", "510000", "批发", 1.00, 500),
    ("SC-CD", "成都青石桥农贸市场", "510000", "零售", 1.31, 170),
    ("GD-JN", "广东江南果菜批发市场", "440000", "批发", 1.00, 620),
    ("GD-GZ", "广州东川新街市", "440000", "零售", 1.34, 190),
    ("HB-BSZ", "湖北白沙洲农副产品批发市场", "420000", "批发", 1.00, 540),
    ("HB-WH", "武汉中百仓储生鲜集市", "420000", "零售", 1.29, 160),
]

GEN = {
    "生猪": {"amp": 0.10, "peak": 20, "sigma": 0.012, "drift": 0.05,
              "cycle_amp": 0.11, "cycle_period": 1150, "cycle_phase": 0.4,
              "shocks": [("2023-10-20", "2023-12-10", 0.10), ("2025-05-01", "2025-06-15", -0.07)]},
    "鸡蛋": {"amp": 0.13, "peak": 250, "sigma": 0.014, "drift": 0.03,
              "cycle_amp": 0.06, "cycle_period": 760, "cycle_phase": 1.2,
              "shocks": [("2025-08-15", "2025-09-15", 0.14), ("2024-02-01", "2024-02-20", 0.09)]},
    "大白菜": {"amp": 0.34, "peak": 18, "sigma": 0.030, "drift": 0.02,
                "cycle_amp": 0.0, "cycle_period": 1200, "cycle_phase": 0.0,
                "shocks": [("2024-01-05", "2024-01-30", 0.20), ("2025-01-20", "2025-02-15", 0.15),
                           ("2026-01-10", "2026-02-05", 0.18), ("2024-07-10", "2024-07-25", -0.12)]},
    "富士苹果": {"amp": 0.12, "peak": 120, "sigma": 0.010, "drift": 0.03,
                  "cycle_amp": 0.04, "cycle_period": 900, "cycle_phase": 2.0,
                  "shocks": [("2026-04-10", "2026-04-30", 0.09)]},
    "小麦": {"amp": 0.05, "peak": 200, "sigma": 0.006, "drift": 0.02,
              "cycle_amp": 0.0, "cycle_period": 1200, "cycle_phase": 0.0,
              "shocks": [("2025-06-01", "2025-06-20", 0.06)]},
}

SPRING_FESTIVALS = [date(2023, 1, 22), date(2024, 2, 10), date(2025, 1, 29), date(2026, 2, 17)]
MID_AUTUMNS = [date(2023, 9, 29), date(2024, 9, 17), date(2025, 10, 6), date(2026, 9, 25)]

PERMISSIONS = [
    ("dashboard:view", "综合驾驶舱", "看板"),
    ("monitor:view", "价格监测查看", "监测"),
    ("monitor:export", "价格数据导出", "监测"),
    ("forecast:view", "预测结果查看", "预测"),
    ("forecast:run", "执行预测", "预测"),
    ("model:manage", "模型训练与启停", "预测"),
    ("alert:view", "预警查看", "预警"),
    ("alert:handle", "预警处置", "预警"),
    ("alert:rule", "预警规则配置", "预警"),
    ("scenario:view", "情景推演查看", "情景"),
    ("scenario:run", "执行情景推演", "情景"),
    ("report:view", "报告查看", "报告"),
    ("report:generate", "报告生成", "报告"),
    ("data:view", "数据治理查看", "治理"),
    ("data:import", "数据导入", "治理"),
    ("data:source", "数据源维护", "治理"),
    ("admin:user", "用户管理", "后台"),
    ("admin:role", "角色权限", "后台"),
    ("admin:base", "品种与地区维护", "后台"),
    ("admin:audit", "审计日志", "后台"),
    ("admin:task", "任务调度", "后台"),
]

ROLE_DEFS = {
    "admin": {"name": "系统管理员", "description": "平台全量权限，负责账号、角色、基础数据与系统运维",
              "perms": "ALL"},
    "analyst": {"name": "价格分析师", "description": "价格监测、预测建模、预警查看、情景与报告",
                "perms": ["dashboard:view", "monitor:view", "monitor:export", "forecast:view", "forecast:run",
                          "model:manage", "alert:view", "scenario:view", "scenario:run", "report:view",
                          "report:generate", "data:view"]},
    "operator": {"name": "监测员", "description": "日常价格监测、预警处置与数据导入",
                 "perms": ["dashboard:view", "monitor:view", "monitor:export", "alert:view", "alert:handle",
                           "alert:rule", "report:view", "scenario:view", "data:view", "data:import"]},
    "viewer": {"name": "领导/访客", "description": "只读访问驾驶舱、监测、预测与报告",
               "perms": ["dashboard:view", "monitor:view", "forecast:view", "alert:view", "report:view",
                         "scenario:view"]},
}

USERS = [
    ("admin", "Admin@2026", "系统管理员", "admin", "信息中心", "13800000001", "admin@agri.gov.cn"),
    ("analyst01", "Analyst@2026", "张明", "analyst", "市场监测部", "13800000002", "zhangming@agri.gov.cn"),
    ("analyst02", "Analyst@2026", "陈晓", "analyst", "预测建模组", "13800000003", "chenxiao@agri.gov.cn"),
    ("operator01", "Operator@2026", "李婷", "operator", "监测科", "13800000004", "liting@agri.gov.cn"),
    ("operator02", "Operator@2026", "刘洋", "operator", "监测科", "13800000005", "liuyang@agri.gov.cn"),
    ("viewer01", "Viewer@2026", "王建国", "viewer", "综合处", "13800000006", "wangjianguo@agri.gov.cn"),
    ("viewer02", "Viewer@2026", "赵磊", "viewer", "信息中心", "13800000007", "zhaolei@agri.gov.cn"),
]

MENUS = [
    # (key, title, path, icon, permission, parent, sort)
    ("dashboard", "综合驾驶舱", "/dashboard", "Odometer", "dashboard:view", "", 10),
    ("monitor", "价格监测", "/monitor", "TrendCharts", "monitor:view", "", 20),
    ("monitor-prices", "价格监测", "/monitor/prices", "TrendCharts", "", "monitor", 21),
    ("monitor-analysis", "监测分析", "/monitor/analysis", "DataLine", "", "monitor", 22),
    ("forecast", "预测分析", "/forecast", "DataAnalysis", "forecast:view", "", 30),
    ("forecast-short", "短期预测", "/forecast/short", "MagicStick", "", "forecast", 31),
    ("forecast-batch", "批量预测", "/forecast/batch", "Files", "", "forecast", 32),
    ("forecast-models", "模型管理", "/forecast/models", "Cpu", "", "forecast", 33),
    ("alert", "预警管理", "/alert", "Bell", "alert:view", "", 40),
    ("alert-list", "预警列表", "/alert/list", "Bell", "", "alert", 41),
    ("alert-rules", "预警规则", "/alert/rules", "SetUp", "", "alert", 42),
    ("scenario", "情景推演", "/scenario", "Compass", "scenario:view", "", 50),
    ("report", "报告中心", "/report", "Document", "report:view", "", 60),
    ("data", "数据治理", "/data", "Coin", "data:view", "", 70),
    ("data-sources", "数据源管理", "/data/sources", "Connection", "", "data", 71),
    ("data-quality", "数据质量", "/data/quality", "Warning", "", "data", 72),
    ("data-import", "数据导入", "/data/import", "Upload", "", "data", 73),
    ("admin", "后台管理", "/admin", "Setting", "admin:user", "", 80),
    ("admin-users", "用户管理", "/admin/users", "User", "", "admin", 81),
    ("admin-roles", "角色权限", "/admin/roles", "Lock", "", "admin", 82),
    ("admin-base", "品种与地区", "/admin/base", "Grid", "", "admin", 83),
    ("admin-audit", "审计日志", "/admin/audit", "Tickets", "", "admin", 84),
    ("admin-tasks", "任务调度", "/admin/tasks", "Timer", "", "admin", 85),
    ("open-api", "开放 API", "/open-api", "Link", "", "", 90),
]

SOURCES = [
    ("全国农产品批发市场价格信息系统", "平台接口", "REST", "农业农村部信息中心", "正常", "部级批发市场价格日度采集接口"),
    ("省级价格监测平台", "授权接口", "HTTPS", "省发展改革委价格监测中心", "正常", "省级监测点价格数据按日推送"),
    ("批发市场日报填报", "人工填报", "表单", "市场管理方", "正常", "重点批发市场每日行情填报"),
    ("历史价格资料导入", "文件导入", "CSV", "信息中心", "正常", "历年价格台账批量导入通道"),
    ("期货行情参考", "第三方接口", "WebSocket", "期货交易所行情服务", "延迟", "生猪、小麦、苹果期货主力合约参考"),
]

SCHEDULED_TASKS = [
    ("sync_price", "价格数据同步", "0 6 * * *", "每日 06:00 拉取各数据源价格并入库", 1, "成功：同步 268 条"),
    ("alert_scan", "预警规则扫描", "0 8 * * *", "每日 08:00 扫描预警规则并生成预警", 1, "成功：生成 12 条预警"),
    ("model_retrain", "模型周度回训", "0 2 * * 1", "每周一 02:00 重训全部品种模型并更新在用版本", 2, "成功：更新 30 个在用模型"),
    ("report_daily", "日报自动生成", "30 7 * * *", "每日 07:30 生成前一日价格监测日报", 1, "成功：生成日报 1 份"),
    ("quality_check", "数据质量巡检", "0 3 * * *", "每日 03:00 巡检缺失、重复与异常值", 1, "成功：发现异常 6 条"),
]


# ---------------------------- 生成工具 ----------------------------

def _ar1(n: int, sigma: float, phi: float, rng: np.random.Generator) -> np.ndarray:
    eps = rng.normal(0, sigma, n)
    out = np.empty(n)
    out[0] = eps[0]
    for i in range(1, n):
        out[i] = phi * out[i - 1] + eps[i]
    return out


def _shock_curve(dates: pd.DatetimeIndex, shocks: list[tuple[str, str, float]]) -> np.ndarray:
    curve = np.ones(len(dates))
    index = {d: i for i, d in enumerate(dates)}
    for begin, end, factor in shocks:
        i0 = index.get(pd.Timestamp(begin))
        i1 = index.get(pd.Timestamp(end))
        if i0 is None or i1 is None or i1 <= i0:
            continue
        seg = np.arange(i0, i1 + 1)
        ramp = np.minimum(1.0, (seg - i0 + 1) / 8.0) * np.minimum(1.0, (i1 - seg + 1) / 8.0)
        curve[seg] *= 1 + factor * ramp
    return curve


def _holiday_curve(dates: pd.DatetimeIndex) -> np.ndarray:
    curve = np.ones(len(dates))
    for i, ts in enumerate(dates):
        d = ts.date()
        effect = 0.0
        for fest in SPRING_FESTIVALS:
            off = abs((d - fest).days)
            if off <= 16:
                effect += 0.045 * math.exp(-off / 6.0)
        for mid in MID_AUTUMNS:
            off = abs((d - mid).days)
            if off <= 10:
                effect += 0.02 * math.exp(-off / 4.0)
        if (d.month == 9 and d.day >= 29) or (d.month == 10 and d.day <= 6):
            effect += 0.025
        if (d.month == 12 and d.day >= 30) or (d.month == 1 and d.day <= 2):
            effect += 0.015
        curve[i] = 1 + effect
    return curve


def _weekly_retail(dates: pd.DatetimeIndex) -> np.ndarray:
    wd = dates.day_of_week.to_numpy()
    out = np.ones(len(dates))
    out[wd == 4] += 0.006
    out[wd == 5] += 0.008
    out[wd == 6] -= 0.004
    out[wd == 0] -= 0.003
    return out


def build_prices_and_features() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rng = np.random.default_rng(RNG_SEED)
    dates = pd.date_range(pd.Timestamp(START), pd.Timestamp(END), freq="D")
    n = len(dates)
    t = np.arange(n)
    doy = dates.day_of_year.to_numpy()
    weekly = _weekly_retail(dates)
    holiday = _holiday_curve(dates)

    market_id = {code: i + 1 for i, (code, *_rest) in enumerate(MARKETS)}
    region_markets: dict[str, list[tuple]] = {}
    for m in MARKETS:
        region_markets.setdefault(m[2], []).append(m)

    freight_index = 100 + 5 * np.sin(2 * math.pi * t / 420 + 0.8) + 3 * np.sin(2 * math.pi * t / 150) + _ar1(n, 0.5, 0.92, rng)

    price_frames: list[pd.DataFrame] = []
    feature_frames: list[pd.DataFrame] = []
    wholesale_series: dict[tuple[int, int], np.ndarray] = {}

    for vi, (vcode, vname, category, base, vol_factor) in enumerate(VARIETIES, start=1):
        g = GEN[vname]
        season = 1 + g["amp"] * np.sin(2 * math.pi * (doy - g["peak"]) / 365.25)
        trend = 1 + g["drift"] * (t / (n - 1) - 0.5)
        cycle = 1 + g["cycle_amp"] * np.sin(2 * math.pi * t / g["cycle_period"] + g["cycle_phase"])
        noise = _ar1(n, g["sigma"], 0.93, rng)
        shock = _shock_curve(dates, g["shocks"])
        master = base * season * trend * cycle * (1 + noise) * shock * holiday
        master = np.maximum(master, base * 0.25)

        cost_index = 100 + 9 * np.sin(2 * math.pi * t / 760 + vi) + _ar1(n, 0.8, 0.9, rng)
        weather = np.clip(100 - 45 * np.maximum(shock - 1, 0) - 8 * np.maximum(1 - shock, 0) + _ar1(n, 1.4, 0.85, rng), 30, 100)
        futures_factor = {"生猪": 1.05, "小麦": 1.02, "富士苹果": 1.06}.get(vname, 0.0)

        for ri, (rcode, rname, rfactor, rsize) in enumerate(REGIONS, start=1):
            reg = master * rfactor * (1 + _ar1(n, 0.007, 0.95, rng))
            wholesale_series[(vi, ri)] = reg

            for (mcode, mname, mregion, mtype, mfactor, mvol) in region_markets[rcode]:
                if mtype == "批发":
                    price = reg * (1 + _ar1(n, 0.004, 0.9, rng))
                else:
                    price = reg * mfactor * (1 + _ar1(n, 0.005, 0.9, rng)) * weekly
                price = np.maximum(price, base * 0.2)

                flag = np.full(n, "正常", dtype=object)
                k1 = rng.random(n) < 0.004
                price[k1] *= 1.18 + rng.random(int(k1.sum())) * 0.12
                flag[k1] = "疑似异常"
                k2 = rng.random(n) < 0.0025
                idx2 = np.where(k2)[0]
                idx2 = idx2[idx2 > 0]
                if len(idx2):
                    price[idx2] = price[idx2 - 1]
                    flag[idx2] = "缺失估算"

                minp = price * (1 - rng.uniform(0.010, 0.030, n))
                maxp = price * (1 + rng.uniform(0.010, 0.030, n))
                volume = (mvol * vol_factor * rsize) * np.exp(rng.normal(0, 0.35, n))
                sources = rng.choice([1, 2, 3, 4], size=n, p=[0.45, 0.25, 0.20, 0.10])

                price_frames.append(pd.DataFrame({
                    "variety_id": vi,
                    "region_id": ri,
                    "market_id": market_id[mcode],
                    "market_type": mtype,
                    "price_date": dates.date,
                    "price": np.round(price, 2),
                    "min_price": np.round(minp, 2),
                    "max_price": np.round(maxp, 2),
                    "volume": np.round(volume, 1),
                    "unit": "元/公斤",
                    "source_id": sources,
                    "quality_flag": flag,
                    "created_at": NOW,
                }))

            # 特征基于地区批发价格序列
            p = pd.Series(reg, index=dates)
            yoy = (p / p.shift(365) - 1) * 100
            mom = (p / p.shift(30) - 1) * 100
            vol30 = p.pct_change().rolling(30).std() * 100
            seasonal_idx = p / p.rolling(365, min_periods=200).mean() * 100
            futures = p * futures_factor * (1 + _ar1(n, 0.01, 0.9, rng)) if futures_factor else pd.Series(0.0, index=dates)
            mask = dates >= pd.Timestamp(FEATURE_START)
            feature_frames.append(pd.DataFrame({
                "variety_id": vi,
                "region_id": ri,
                "calc_date": dates[mask].date,
                "yoy_pct": np.round(yoy[mask].fillna(0).to_numpy(), 2),
                "mom_pct": np.round(mom[mask].fillna(0).to_numpy(), 2),
                "volatility_30d": np.round(vol30[mask].fillna(0).to_numpy(), 2),
                "seasonal_index": np.round(seasonal_idx[mask].fillna(100).to_numpy(), 1),
                "cost_index": np.round(cost_index[mask], 1),
                "freight_index": np.round(freight_index[mask], 1),
                "weather_score": np.round(weather[mask], 1),
                "futures_price": np.round(futures[mask].to_numpy(), 2),
                "holiday_flag": (holiday[mask] != 1.0).astype(int),
            }))

    prices = pd.concat(price_frames, ignore_index=True)
    features = pd.concat(feature_frames, ignore_index=True)
    return prices, features, {"wholesale": wholesale_series, "dates": dates}


# ---------------------------- 主数据 ----------------------------

def seed_reference(db: Session) -> None:
    for key, name, desc in [(k, v["name"], v["description"]) for k, v in ROLE_DEFS.items()]:
        db.merge(Role(key=key, name=name, description=desc))
    db.commit()

    for i, (key, name, module) in enumerate(PERMISSIONS):
        db.merge(Permission(key=key, name=name, module=module, sort=i))
    db.commit()

    for role_key, cfg in ROLE_DEFS.items():
        perms = [p[0] for p in PERMISSIONS] if cfg["perms"] == "ALL" else cfg["perms"]
        for perm in perms:
            db.add(RolePermission(role_key=role_key, perm_key=perm))
    db.commit()

    for key, title, path, icon, permission, parent, sort in MENUS:
        db.merge(Menu(key=key, title=title, path=path, icon=icon, permission=permission, parent_key=parent, sort=sort))
    db.commit()

    for i, (code, name, cat, _base, _vol) in enumerate(VARIETIES, start=1):
        db.merge(Variety(id=i, code=code, name=name, category=cat, unit="元/公斤", enabled=True, sort=i))
    for i, (code, name, _f, _s) in enumerate(REGIONS, start=1):
        db.merge(Region(id=i, code=code, name=name, level="省级", enabled=True, sort=i))
    db.commit()

    for i, (code, name, rcode, mtype, _f, _v) in enumerate(MARKETS, start=1):
        db.merge(Market(id=i, code=code, name=name, region_code=rcode, market_type=mtype, enabled=True))
    db.commit()

    for i, (username, password, display_name, role_key, org, phone, email) in enumerate(USERS, start=1):
        db.merge(User(id=i, username=username, password_hash=hash_password(password),
                      display_name=display_name, role_key=role_key, org=org, phone=phone, email=email,
                      status="启用", created_at=NOW - timedelta(days=200 - i * 7)))
    db.commit()

    for i, (name, stype, protocol, owner, status, desc) in enumerate(SOURCES, start=1):
        db.merge(DataSource(id=i, name=name, type=stype, protocol=protocol, owner=owner, status=status,
                            last_sync_at=NOW - timedelta(hours=i * 5), record_count=0,
                            description=desc, created_at=NOW - timedelta(days=300)))
    db.commit()


def seed_prices(db: Session, prices: pd.DataFrame, features: pd.DataFrame) -> None:
    # MySQL 下 pymysql 的 executemany 会把整批参数合并成单条多行 INSERT
    # （每批 5000 行 ≈ 一条语句），比显式 method="multi" 少一层 SQL 拼装开销：
    # 实测 84,660 行价格入库 executemany 约 3.7s，method="multi"(chunksize=2000)
    # 约 13.8s。分批大小 5000 时单条语句约 1MB，仍远低于 max_allowed_packet。
    prices.to_sql("price_record", engine, if_exists="append", index=False, chunksize=5000)
    features.to_sql("feature_record", engine, if_exists="append", index=False, chunksize=5000)
    db.commit()
    for i, (name, *_rest) in enumerate(SOURCES, start=1):
        source = db.get(DataSource, i)
        if source:
            source.record_count = int(db.scalar(select(func.count()).select_from(PriceRecord).where(PriceRecord.source_id == i)) or 0)
    db.commit()


def seed_governance(db: Session) -> None:
    flagged = db.execute(
        select(PriceRecord).where(PriceRecord.quality_flag != "正常").limit(48)
    ).scalars().all()
    for idx, row in enumerate(flagged):
        status = "已处理" if idx % 3 == 0 else "待处理"
        db.add(QualityIssue(
            price_id=row.id,
            variety_id=row.variety_id,
            region_id=row.region_id,
            issue_date=row.price_date,
            issue_type="价格异常波动" if row.quality_flag == "疑似异常" else "数据缺失估算",
            detail=("当日价格较前一日波动超过 18%，已标记待复核"
                    if row.quality_flag == "疑似异常" else "数据源缺失，按前一日价格估算补全"),
            status=status,
            resolved_by="李婷" if status == "已处理" else "",
            resolved_at=NOW - timedelta(days=idx % 9) if status == "已处理" else None,
        ))

    import_tasks = [
        ("全国批发价格_20261109.csv", 320, 320, 0, "已完成", []),
        ("批发市场行情_20261107.csv", 256, 251, 5, "部分成功",
         [{"row": 18, "message": "价格为空"}, {"row": 52, "message": "日期格式不正确"},
          {"row": 96, "message": "地区编码不存在"}, {"row": 171, "message": "价格超出合理区间"},
          {"row": 203, "message": "重复记录"}]),
        ("历史台账_2023Q1.csv", 900, 900, 0, "已完成", []),
    ]
    for i, (filename, total, ok_rows, err_rows, status, errors) in enumerate(import_tasks):
        db.add(ImportTask(
            source_id=4 if i == 2 else (1 if i == 0 else 3),
            filename=filename, rows_total=total, rows_ok=ok_rows, rows_error=err_rows,
            status=status, errors=json.dumps(errors, ensure_ascii=False),
            created_by="李婷", created_at=NOW - timedelta(days=i + 1, hours=2),
        ))

    for i, (key, name, cron, desc, status_idx, last_result) in enumerate(SCHEDULED_TASKS):
        db.add(ScheduledTask(
            key=key, name=name, cron=cron,
            status="启用" if status_idx == 1 else "暂停",
            last_run_at=NOW - timedelta(hours=9 + i * 3),
            last_result=last_result,
            next_run_at=NOW + timedelta(hours=6 + i * 2),
            description=desc,
        ))

    audits = [
        ("admin", "登录", "认证", "账号 admin 登录系统"),
        ("analyst01", "执行预测", "预测", "生猪·北京 未来 14 天价格预测"),
        ("operator01", "处置预警", "预警", "大白菜价格快速上涨预警已核实并闭环"),
        ("analyst01", "生成报告", "报告", "生成 2026-11-10 价格监测日报"),
        ("admin", "新增用户", "后台", "创建用户 operator02"),
        ("operator02", "导入数据", "治理", "导入 批发市场行情_20261107.csv，成功 251 条"),
        ("analyst02", "模型训练", "预测", "重训 鸡蛋·山东 组合模型"),
        ("operator01", "解决异常", "治理", "标记 3 条价格异常记录为已处理"),
        ("admin", "修改角色权限", "后台", "调整监测员角色权限点"),
        ("viewer01", "登录", "认证", "账号 viewer01 登录系统"),
        ("analyst01", "调整预警规则", "预警", "修改 生猪价格低位预警 阈值"),
        ("operator01", "数据源巡检", "治理", "期货行情参考接口延迟，已记录"),
        ("analyst02", "情景推演", "情景", "寒潮冲击下大白菜价格情景推演"),
        ("admin", "重置密码", "后台", "重置用户 operator02 登录密码"),
        ("operator02", "处置预警", "预警", "鸡蛋同比异常预警误报，已关闭"),
        ("analyst01", "导出数据", "监测", "导出 2026 年 10 月价格监测数据"),
        ("admin", "任务调度", "后台", "手动执行 价格数据同步 任务"),
        ("analyst02", "执行预测", "预测", "批量预测 5 品种×6 地区 未来 14 天"),
    ]
    for i, (username, action, module, detail) in enumerate(audits):
        db.add(AuditLog(
            user_id=next((u[0] for u in enumerate(USERS, start=1) if u[1][0] == username), 0),
            username=username, action=action, module=module, detail=detail,
            ip="127.0.0.1", created_at=NOW - timedelta(days=i // 3, hours=(i * 5) % 24, minutes=(i * 17) % 60),
        ))
    db.commit()


# ---------------------------- 预警与报告 ----------------------------

def seed_alert_rules(db: Session, prices: pd.DataFrame, features: pd.DataFrame) -> list[AlertRule]:
    def q(series: pd.Series, quantile: float, digits: int = 2) -> float:
        return round(float(series.quantile(quantile)), digits)

    recent = prices[prices["price_date"] >= (END - timedelta(days=120))]
    recent_feat = features[features["calc_date"] >= (END - timedelta(days=120))]
    pig_price = recent[(recent.variety_id == 1) & (recent.market_type == "批发")]["price"]
    cabbage_vol = recent_feat[recent_feat.variety_id == 3]["volatility_30d"]
    egg_yoy = recent_feat[recent_feat.variety_id == 2]["yoy_pct"].abs()
    pig_vol = recent_feat[recent_feat.variety_id == 1]["volatility_30d"]
    wheat_price = recent[(recent.variety_id == 5) & (recent.market_type == "批发")]["price"]
    apple_wholesale = recent[(recent.variety_id == 4) & (recent.market_type == "批发")]
    spread = apple_wholesale.groupby("price_date")["price"].agg(lambda s: s.max() - s.min())

    rules = [
        dict(name="生猪价格低位预警", variety_id=1, region_id=None, rule_type="price_threshold",
             operator="lt", threshold=q(pig_price, 0.06), window_days=1, level="高",
             channel="站内消息+短信", created_by="admin"),
        dict(name="生猪价格波动率异常", variety_id=1, region_id=None, rule_type="volatility",
             operator="abs_gt", threshold=q(pig_vol, 0.96), window_days=30, level="中",
             channel="站内消息", created_by="admin"),
        dict(name="大白菜价格快速上涨", variety_id=3, region_id=None, rule_type="volatility",
             operator="abs_gt", threshold=q(cabbage_vol, 0.97), window_days=30, level="中",
             channel="站内消息+邮件", created_by="analyst01"),
        dict(name="鸡蛋同比异常预警", variety_id=2, region_id=None, rule_type="yoy",
             operator="abs_gt", threshold=q(egg_yoy, 0.97, 1), window_days=30, level="高",
             channel="站内消息+短信", created_by="analyst01"),
        dict(name="富士苹果区域价差预警", variety_id=4, region_id=None, rule_type="spread",
             operator="gt", threshold=q(spread, 0.95), window_days=30, level="低",
             channel="站内消息", created_by="operator01"),
        dict(name="小麦价格高位预警", variety_id=5, region_id=None, rule_type="price_threshold",
             operator="gt", threshold=q(wheat_price, 0.92), window_days=1, level="中",
             channel="站内消息", created_by="operator01"),
    ]
    created: list[AlertRule] = []
    for item in rules:
        rule = AlertRule(**item)
        db.add(rule)
        created.append(rule)
    db.commit()
    return created


def seed_fallback_alerts(db: Session, rules: list[AlertRule]) -> None:
    """算法服务尚未就绪时的兜底预警，保证页面有可看数据。"""
    samples = [
        (0, 1, 1, "生猪价格低位预警", "北京生猪批发价 15.42 元/公斤，低于阈值 15.8 元/公斤", "高", "待处理"),
        (2, 3, 4, "大白菜价格快速上涨", "广东大白菜批发价周内上涨 21.6%，波动率超阈值", "中", "待处理"),
        (3, 2, 2, "鸡蛋同比异常预警", "山东鸡蛋价格同比上涨 19.8%，超过异常阈值", "高", "处理中"),
        (5, 5, 5, "小麦价格高位预警", "湖北小麦批发价 3.12 元/公斤，高于预警阈值", "中", "待处理"),
        (4, 4, 3, "富士苹果区域价差预警", "河南与广东富士苹果价差 2.46 元/公斤，超过阈值", "低", "已关闭"),
        (1, 1, 6, "生猪价格波动率异常", "湖北生猪日波动率连续 3 日超过阈值", "中", "待处理"),
    ]
    for i, (rule_idx, vid, rid, title, detail, level, status) in enumerate(samples):
        db.add(AlertRecord(
            rule_id=rules[rule_idx].id if rule_idx < len(rules) else 1,
            variety_id=vid, region_id=rid,
            alert_date=END - timedelta(days=i * 2 + 1), level=level, title=title, detail=detail,
            status=status, handler="李婷" if status != "待处理" else "",
            handled_at=NOW - timedelta(days=i) if status != "待处理" else None,
            handle_note="已通知属地监测点核查" if status != "待处理" else "",
            notify_channel="站内消息", created_at=NOW - timedelta(days=i * 2 + 1),
        ))
    db.commit()


def _fallback_reports(db: Session) -> None:
    daily_metrics = {"kpi": [("监测品种", 5), ("覆盖市场", 12), ("当日均价指数", 106.3), ("在途预警", 5)]}
    reports = [
        ("2026-11-10 农产品价格监测日报", "daily", END - timedelta(days=1), END - timedelta(days=1),
         "当日重点监测品种价格整体平稳，生猪价格小幅回落，大白菜受降温影响上涨 3.8%。"),
        ("2026 年第 45 周价格监测周报", "weekly", END - timedelta(days=7), END - timedelta(days=1),
         "本周农产品综合价格指数环比上涨 1.2%，鸡蛋、大白菜涨幅居前，小麦价格保持稳定。"),
        ("2026 年 10 月价格监测月报", "monthly", date(2026, 10, 1), date(2026, 10, 31),
         "10 月综合价格指数同比上涨 3.4%，生猪产能恢复带动价格回落，蔬菜价格季节性上行。"),
    ]
    for title, report_type, ps, pe, summary in reports:
        db.add(Report(
            title=title, report_type=report_type, period_start=ps, period_end=pe,
            variety_ids="1,2,3,4,5", region_ids="1,2,3,4,5,6", status="已发布",
            summary=summary, metrics=json.dumps(daily_metrics, ensure_ascii=False),
            created_by="system", created_at=NOW - timedelta(days=9),
        ))
    db.commit()


def seed_derived(db: Session, with_models: bool = True) -> None:
    """预警扫描、报告生成、模型训练与示例预测（算法模块就绪时自动生效）。"""
    try:
        from .services.alerting import evaluate_rules
        result = evaluate_rules(db, days=30)
        print(f"[seed] 预警扫描完成：新增 {result.get('created')} 条")
        if not result.get("created"):
            rules = db.execute(select(AlertRule)).scalars().all()
            seed_fallback_alerts(db, rules)
    except Exception as exc:  # pragma: no cover - 算法模块未就绪
        print(f"[seed] 预警扫描跳过：{exc}")
        rules = db.execute(select(AlertRule)).scalars().all()
        if rules and not db.scalar(select(func.count()).select_from(AlertRecord)):
            seed_fallback_alerts(db, rules)

    try:
        from .services.reporting import generate_report
        generate_report(db, None, "daily", period_start=END - timedelta(days=1), period_end=END - timedelta(days=1))
        generate_report(db, None, "weekly", period_start=END - timedelta(days=7), period_end=END - timedelta(days=1))
        generate_report(db, None, "monthly", period_start=date(2026, 10, 1), period_end=date(2026, 10, 31))
        print("[seed] 报告生成完成")
    except Exception as exc:  # pragma: no cover
        print(f"[seed] 报告生成跳过：{exc}")
        if not db.scalar(select(func.count()).select_from(Report)):
            _fallback_reports(db)

    if not with_models:
        return
    try:
        from .services.forecasting import ensure_active_models
        models = ensure_active_models(db)
        print(f"[seed] 模型训练完成：{len(models)} 个在用模型")
    except Exception as exc:  # pragma: no cover
        print(f"[seed] 模型训练跳过：{exc}")
        return
    try:
        from .services.forecasting import run_forecast
        for vid in range(1, 6):
            run_forecast(db, None, vid, 1, 14)
        print("[seed] 示例预测生成完成")
    except Exception as exc:  # pragma: no cover
        print(f"[seed] 示例预测跳过：{exc}")


# ---------------------------- 入口 ----------------------------

def seed_all(db: Session, with_models: bool = True) -> dict:
    seed_reference(db)
    prices, features, _extra = build_prices_and_features()
    seed_prices(db, prices, features)
    seed_governance(db)
    seed_alert_rules(db, prices, features)
    seed_derived(db, with_models=with_models)

    stats = {t: int(db.scalar(select(func.count()).select_from(m)) or 0) for t, m in [
        ("varieties", Variety), ("regions", Region), ("markets", Market), ("users", User),
        ("prices", PriceRecord), ("features", FeatureRecord), ("alerts", AlertRecord),
        ("reports", Report), ("audit_logs", AuditLog),
    ]}
    print("[seed] 数据统计：" + json.dumps(stats, ensure_ascii=False))
    return stats


def ensure_initialized() -> bool:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return False
        print("[seed] 检测到空数据库，开始生成种子数据（首次启动约需 1-3 分钟）")
        seed_all(db)
        return True


def reset_business_data(db: Session) -> None:
    """清空全部业务表；MySQL 下同时复位 AUTO_INCREMENT。

    MySQL 使用 ``SET FOREIGN_KEY_CHECKS=0`` + ``TRUNCATE``：TRUNCATE 会重置
    AUTO_INCREMENT，且比逐表 DELETE 快得多；SQLite 保留反序 DELETE 并尽力
    清理 ``sqlite_sequence``。
    """
    if IS_SQLITE:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
        db.commit()
        try:  # 使用 INTEGER PRIMARY KEY（非 AUTOINCREMENT）时没有 sqlite_sequence
            db.execute(text("DELETE FROM sqlite_sequence"))
            db.commit()
        except OperationalError:
            db.rollback()
        return

    # MySQL：TRUNCATE 是 DDL（隐式提交），因此用独立连接并临时关闭外键检查。
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table in Base.metadata.sorted_tables:
                conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        finally:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def main() -> None:
    parser = argparse.ArgumentParser(description="农产品价格平台种子数据")
    parser.add_argument("--reset", action="store_true", help="清空全部数据后重建")
    parser.add_argument("--no-models", action="store_true", help="跳过模型训练（快速建库）")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if args.reset:
            print("[seed] 清空业务数据…")
            reset_business_data(db)
        elif db.scalar(select(func.count()).select_from(User)):
            print("[seed] 数据库已有数据，如需重建请使用 --reset")
            return
        seed_all(db, with_models=not args.no_models)


if __name__ == "__main__":
    main()
