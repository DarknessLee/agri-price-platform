"""情景推演服务（契约 §8「情景推演」）。

在基准预测（active 组合模型）之上叠加外生冲击，输出情景价格路径与影响评估：
    冲击系数 e = 1 + 需求冲击×0.6% - 供给冲击×0.8% + 运费冲击×0.1%
    情景价_t   = 基准价_t × (1 + (e-1) × 逐日累积权重_t)
累积权重按 logistics 曲线在推演期内逐步释放（约 7 天接近满幅，后期小幅衰减），
用于刻画"冲击传导需要时间、且存在衰减"的现实特征。

冲击字段映射（契约 shock 结构）：
- yield_pct      产量变化（%），正值为增产 → 供给冲击 supply_shock
- weather_level  气象等级 0~3，等级越高额外减产 0/2/5/9 个百分点 → 计入供给冲击
- substitute_pct 替代品价格变化（%），正值为替代品涨价 → 需求冲击（需求转移）
- policy_pct     政策冲击（%），正值为收储/补贴等需求侧利好 → 计入需求冲击
- freight_pct    运费变化（%）→ 运费冲击
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import now
from ..models import Region, ScenarioSim, Variety
from ..security import ApiError
from . import forecasting

SCENARIO_TYPES: dict[str, str] = {
    "weather": "气象灾害",
    "freight": "运费波动",
    "policy": "政策调控",
    "substitute": "替代品冲击",
}

WEATHER_EXTRA_YIELD: dict[int, float] = {0: 0.0, 1: -2.0, 2: -5.0, 3: -9.0}
SUPPLY_COEF = 0.008   # 供给每变动 1%，价格反向变动 0.8%
DEMAND_COEF = 0.006   # 需求每变动 1%，价格同向变动 0.6%
FREIGHT_COEF = 0.001  # 运费每变动 1%，价格同向变动 0.1%
MAX_SHOCK = 30.0
MAX_HORIZON = 90

SCENARIO_TEMPLATES: list[dict] = [
    {
        "key": "weather",
        "name": "气象灾害",
        "description": "主产区持续强降雨/寒潮导致阶段性减产，叠加运输受阻。",
        "defaults": {
            "yield_pct": -8,
            "weather_level": 2,
            "freight_pct": 6,
            "substitute_pct": 0,
            "policy_pct": 0,
        },
    },
    {
        "key": "freight",
        "name": "运费波动",
        "description": "油价上涨或运力紧张推高跨区域调运成本。",
        "defaults": {
            "yield_pct": 0,
            "weather_level": 0,
            "freight_pct": 18,
            "substitute_pct": 0,
            "policy_pct": 0,
        },
    },
    {
        "key": "policy",
        "name": "政策调控",
        "description": "储备收储/投放或补贴政策改变短期供需格局。",
        "defaults": {
            "yield_pct": 0,
            "weather_level": 0,
            "freight_pct": 0,
            "substitute_pct": 0,
            "policy_pct": 10,
        },
    },
    {
        "key": "substitute",
        "name": "替代品冲击",
        "description": "替代品价格大幅波动带来需求转移。",
        "defaults": {
            "yield_pct": 0,
            "weather_level": 0,
            "freight_pct": 0,
            "substitute_pct": 12,
            "policy_pct": 0,
        },
    },
]


# ============================ 工具 ============================

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        raise ApiError("E4001", "冲击参数必须为数字", 400)


def _clamp_shock(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ApiError("E4001", f"{name}参数不合法", 400)
    return max(-MAX_SHOCK, min(MAX_SHOCK, value))


def _read_json(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (ValueError, TypeError):
        return default
    return value if value is not None else default


def _name_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    varieties = {int(v.id): v.name for v in db.execute(select(Variety)).scalars().all()}
    regions = {int(r.id): r.name for r in db.execute(select(Region)).scalars().all()}
    return varieties, regions


def templates() -> list[dict]:
    return [dict(item) for item in SCENARIO_TEMPLATES]


# ============================ 冲击映射 ============================

def _shock_to_components(shock: dict) -> dict[str, float]:
    """把契约 shock 结构映射为供给/需求/运费三类冲击。"""
    yield_pct = _clamp_shock(_to_float(shock.get("yield_pct")), "产量变化")
    try:
        weather_level = int(_to_float(shock.get("weather_level"), 0))
    except (TypeError, ValueError):
        weather_level = 0
    weather_level = max(0, min(3, weather_level))
    substitute_pct = _clamp_shock(_to_float(shock.get("substitute_pct")), "替代品变化")
    policy_pct = _clamp_shock(_to_float(shock.get("policy_pct")), "政策冲击")
    freight_pct = _clamp_shock(_to_float(shock.get("freight_pct")), "运费变化")

    supply_shock = yield_pct + WEATHER_EXTRA_YIELD.get(weather_level, 0.0)
    demand_shock = substitute_pct + policy_pct
    return {
        "yield_pct": round(yield_pct, 2),
        "weather_level": float(weather_level),
        "weather_yield_pct": WEATHER_EXTRA_YIELD.get(weather_level, 0.0),
        "substitute_pct": round(substitute_pct, 2),
        "policy_pct": round(policy_pct, 2),
        "freight_pct": round(freight_pct, 2),
        "supply_shock": round(supply_shock, 2),
        "demand_shock": round(demand_shock, 2),
        "freight_shock": round(freight_pct, 2),
    }


def _impact_multiplier(components: dict[str, float]) -> float:
    """单日满幅冲击下的价格乘数。"""
    delta = (
        components["demand_shock"] * DEMAND_COEF
        - components["supply_shock"] * SUPPLY_COEF
        + components["freight_shock"] * FREIGHT_COEF
    )
    # 最多放大/缩小 60%，避免极端参数产生失真结果
    delta = max(-0.6, min(0.6, delta))
    return 1.0 + delta


def _cumulative_weight(day: int, horizon: int) -> float:
    """冲击累积权重：前 7 天快速释放，推演末期轻微衰减。"""
    ramp = 1.0 - math.exp(-max(day, 1) / 2.2)
    decay = 1.0 - 0.15 * (max(day, 1) / max(horizon, 1))
    return max(0.0, min(1.0, ramp * decay))


def _risk_level(abs_change: float, base_mape: float = 0.0) -> str:
    if abs_change >= 8.0 or base_mape >= 8.0:
        return "高"
    if abs_change >= 3.0 or base_mape >= 5.0:
        return "中"
    return "低"


def _trend_of(change_pct: float) -> str:
    if change_pct > 1.0:
        return "上涨"
    if change_pct < -1.0:
        return "下跌"
    return "震荡"


def _build_factors(components: dict[str, float], multiplier: float) -> list[dict]:
    """各冲击分量对价格的贡献（百分比）。"""
    factors = [
        {
            "name": "供给冲击",
            "impact_pct": round(-components["supply_shock"] * SUPPLY_COEF * 100.0, 2),
            "description": (
                f"产量变化 {components['yield_pct']:+.1f}%，气象等级 {int(components['weather_level'])}"
                f"（额外减产 {components['weather_yield_pct']:+.1f} 个百分点），合计供给 "
                f"{components['supply_shock']:+.1f}%，按每 1% 供给反向影响价格 0.8% 测算。"
            ),
        },
        {
            "name": "需求冲击",
            "impact_pct": round(components["demand_shock"] * DEMAND_COEF * 100.0, 2),
            "description": (
                f"替代品价格变化 {components['substitute_pct']:+.1f}%、政策冲击 {components['policy_pct']:+.1f}%，"
                f"合计需求 {components['demand_shock']:+.1f}%，按每 1% 需求同向影响价格 0.6% 测算。"
            ),
        },
        {
            "name": "运费冲击",
            "impact_pct": round(components["freight_shock"] * FREIGHT_COEF * 100.0, 2),
            "description": (
                f"运费变化 {components['freight_shock']:+.1f}%，按每 1% 运费同向影响价格 0.1% 测算。"
            ),
        },
    ]
    total = round((multiplier - 1.0) * 100.0, 2)
    factors.append(
        {
            "name": "综合传导",
            "impact_pct": total,
            "description": f"三类冲击叠加后，满幅传导下的价格变动约为 {total:+.2f}%，并按累积曲线在推演期内逐步释放。",
        }
    )
    return factors


def _build_advice(change_pct: float, risk: str, components: dict[str, float], horizon: int) -> list[str]:
    advice: list[str] = []
    if risk == "高":
        advice.append(f"情景价格波动预计达 {change_pct:+.2f}%，建议立即启动应急保供预案，加密价格监测频次。")
    elif risk == "中":
        advice.append(f"情景价格波动约 {change_pct:+.2f}%，建议提前锁定货源并关注{f'{horizon}天内' if horizon else ''}的供需变化。")
    else:
        advice.append(f"情景价格波动约 {change_pct:+.2f}%，市场整体可控，维持常规监测节奏即可。")
    if components["supply_shock"] < 0:
        advice.append("供给端承压，建议核实主产区产量与库存，必要时投放储备平抑价格。")
    if components["supply_shock"] > 0:
        advice.append("供给增加可能带来价格下行压力，建议提醒种植/养殖主体合理安排出货节奏。")
    if components["freight_shock"] > 10:
        advice.append("运费明显上行，建议优化跨区域调运半径，优先就近采购以降低物流成本。")
    if components["demand_shock"] > 8:
        advice.append("需求侧冲击较强，建议关注下游采购节奏与替代品价格，防范短期抢购。")
    if components["demand_shock"] < -8:
        advice.append("需求走弱，建议控制库存周转天数，避免压货。")
    return advice


# ============================ 情景执行 ============================

def run_scenario(
    db: Session,
    user: Any,
    variety_id: int,
    region_id: int,
    supply_shock: float = 0.0,
    demand_shock: float = 0.0,
    freight_shock: float = 0.0,
    horizon: int = 14,
    name: str | None = None,
    scenario_type: str = "weather",
    shock: dict | None = None,
    commit: bool = True,
) -> dict:
    """执行情景推演并持久化 ScenarioSim。

    supply_shock/demand_shock/freight_shock 为百分比（-30~30）；也可直接传契约风格
    的 shock 字典（yield_pct/freight_pct/policy_pct/substitute_pct/weather_level）。
    """
    variety = db.get(Variety, int(variety_id)) if variety_id else None
    region = db.get(Region, int(region_id)) if region_id else None
    if variety is None:
        raise ApiError("E4040", "品种不存在", 404)
    if region is None:
        raise ApiError("E4040", "地区不存在", 404)
    try:
        horizon = int(horizon or 14)
    except (TypeError, ValueError):
        raise ApiError("E4001", "推演步长必须为整数", 400)
    horizon = max(1, min(MAX_HORIZON, horizon))

    if shock is not None:
        if not isinstance(shock, dict):
            raise ApiError("E4001", "冲击参数格式不正确", 400)
        components = _shock_to_components(shock)
    else:
        components = {
            "yield_pct": round(_clamp_shock(_to_float(supply_shock), "供给冲击"), 2),
            "weather_level": 0.0,
            "weather_yield_pct": 0.0,
            "substitute_pct": 0.0,
            "policy_pct": 0.0,
            "freight_pct": round(_clamp_shock(_to_float(freight_shock), "运费冲击"), 2),
            "supply_shock": round(_clamp_shock(_to_float(supply_shock), "供给冲击"), 2),
            "demand_shock": round(_clamp_shock(_to_float(demand_shock), "需求冲击"), 2),
            "freight_shock": round(_clamp_shock(_to_float(freight_shock), "运费冲击"), 2),
        }

    scenario_type = str(scenario_type or "weather")
    if scenario_type not in SCENARIO_TYPES:
        # 未指定时按影响最大的冲击维度归类
        dominant = max(
            (
                ("weather", abs(components["supply_shock"])),
                ("freight", abs(components["freight_shock"])),
                ("substitute", abs(components["demand_shock"])),
            ),
            key=lambda item: item[1],
        )[0]
        scenario_type = dominant

    # 基准预测（复用 active 组合模型；不在此处单独提交事务）
    try:
        payload = forecasting.run_forecast(
            db, user, int(variety_id), int(region_id), horizon, commit=False
        )
    except ApiError as exc:
        if exc.code == "E4001":
            raise ApiError("E4001", "暂无足够价格数据，无法进行情景推演", 400)
        raise
    points = payload.get("forecast") or []
    if not points:
        raise ApiError("E4001", "暂无可用基准预测，无法进行情景推演", 400)

    base_mape = float((payload.get("model") or {}).get("mape") or 0)
    multiplier = _impact_multiplier(components)
    dates: list[str] = []
    base_values: list[float] = []
    predicted: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    for index, point in enumerate(points, start=1):
        weight = _cumulative_weight(index, len(points))
        factor = 1.0 + (multiplier - 1.0) * weight
        base_value = float(point["point"])
        scenario_value = base_value * factor
        dates.append(point["target_date"])
        base_values.append(round(base_value, 2))
        predicted.append(round(max(scenario_value, 0.01), 2))
        lower.append(round(max(float(point["lower"]) * factor, 0.01), 2))
        upper.append(round(float(point["upper"]) * factor, 2))

    price_change_pct = 0.0
    if base_values:
        price_change_pct = (predicted[-1] / base_values[-1] - 1.0) * 100.0 if base_values[-1] else 0.0
    trend = _trend_of(price_change_pct)
    risk_level = _risk_level(abs(price_change_pct), base_mape)
    price_range = {
        "low": round(min(predicted), 2),
        "mid": round(sum(predicted) / len(predicted), 2),
        "high": round(max(predicted), 2),
    }
    factors = _build_factors(components, multiplier)
    advice = _build_advice(price_change_pct, risk_level, components, horizon)
    chart = {
        "dates": dates,
        "base": base_values,
        "predicted": predicted,
        "lower": lower,
        "upper": upper,
    }

    if not name:
        name = f"{variety.name}·{region.name}{SCENARIO_TYPES.get(scenario_type, '情景')}推演"
    name = str(name)[:128]
    created_by = (
        (getattr(user, "display_name", None) or getattr(user, "username", None)) if user else "system"
    ) or "system"

    record = ScenarioSim(
        name=name,
        scenario_type=scenario_type,
        variety_id=int(variety_id),
        region_id=int(region_id),
        horizon=horizon,
        shock=json.dumps(components, ensure_ascii=False),
        price_change_pct=round(price_change_pct, 2),
        price_range=json.dumps(price_range, ensure_ascii=False),
        risk_level=risk_level,
        chart=json.dumps(chart, ensure_ascii=False),
        factors=json.dumps(factors, ensure_ascii=False),
        advice=json.dumps(advice, ensure_ascii=False),
        created_by=str(created_by)[:64],
        created_at=now(),
    )
    db.add(record)
    if commit:
        db.commit()
    else:
        db.flush()

    return {
        "id": record.id,
        "name": record.name,
        "scenario_type": record.scenario_type,
        "scenario_type_name": SCENARIO_TYPES.get(record.scenario_type, record.scenario_type),
        "variety_id": record.variety_id,
        "variety": variety.name,
        "region_id": record.region_id,
        "region": region.name,
        "horizon": record.horizon,
        "price_change_pct": round(float(record.price_change_pct or 0), 2),
        "price_range": price_range,
        "risk_level": risk_level,
        "trend": trend,
        "shock": components,
        "chart": chart,
        "factors": factors,
        "advice": advice,
        "created_by": record.created_by,
        "created_at": record.created_at.strftime("%Y-%m-%dT%H:%M:%S") if record.created_at else "",
    }


def _scenario_response(db: Session, record: ScenarioSim, varieties: dict[int, str], regions: dict[int, str]) -> dict:
    chart = _read_json(record.chart, {"dates": [], "base": [], "predicted": [], "lower": [], "upper": []})
    price_range = _read_json(record.price_range, {"low": 0, "mid": 0, "high": 0})
    factors = _read_json(record.factors, [])
    advice = _read_json(record.advice, [])
    change = float(record.price_change_pct or 0)
    return {
        "id": record.id,
        "name": record.name,
        "scenario_type": record.scenario_type,
        "scenario_type_name": SCENARIO_TYPES.get(record.scenario_type, record.scenario_type),
        "variety_id": record.variety_id,
        "variety": varieties.get(int(record.variety_id), ""),
        "region_id": record.region_id,
        "region": regions.get(int(record.region_id), ""),
        "horizon": record.horizon,
        "price_change_pct": round(change, 2),
        "price_range": price_range,
        "risk_level": record.risk_level,
        "trend": _trend_of(change),
        "shock": _read_json(record.shock, {}),
        "chart": chart,
        "factors": factors,
        "advice": advice,
        "created_by": record.created_by,
        "created_at": record.created_at.strftime("%Y-%m-%dT%H:%M:%S") if record.created_at else "",
    }


def get_scenario(db: Session, scenario_id: int) -> dict:
    record = db.get(ScenarioSim, int(scenario_id))
    if record is None:
        raise ApiError("E4040", "情景推演记录不存在", 404)
    varieties, regions = _name_maps(db)
    return _scenario_response(db, record, varieties, regions)


def list_scenarios(db: Session, page: int = 1, page_size: int = 10) -> tuple[list[dict], int]:
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 10)))
    total = int(db.execute(select(func.count(ScenarioSim.id))).scalar() or 0)
    rows = db.execute(
        select(ScenarioSim)
        .order_by(ScenarioSim.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    varieties, regions = _name_maps(db)
    items = [
        {
            "id": record.id,
            "name": record.name,
            "scenario_type": record.scenario_type,
            "scenario_type_name": SCENARIO_TYPES.get(record.scenario_type, record.scenario_type),
            "variety": varieties.get(int(record.variety_id), ""),
            "region": regions.get(int(record.region_id), ""),
            "horizon": record.horizon,
            "price_change_pct": round(float(record.price_change_pct or 0), 2),
            "risk_level": record.risk_level,
            "created_by": record.created_by,
            "created_at": record.created_at.strftime("%Y-%m-%dT%H:%M:%S") if record.created_at else "",
        }
        for record in rows
    ]
    return items, total


def delete_scenario(db: Session, scenario_id: int, commit: bool = True) -> None:
    record = db.get(ScenarioSim, int(scenario_id))
    if record is None:
        raise ApiError("E4040", "情景推演记录不存在", 404)
    db.delete(record)
    if commit:
        db.commit()
