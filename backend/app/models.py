"""领域模型：权限、主数据、价格、特征、预测、预警、情景、报告、治理与审计。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Role(Base):
    __tablename__ = "sys_role"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")


class Permission(Base):
    __tablename__ = "sys_permission"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(32))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class RolePermission(Base):
    __tablename__ = "sys_role_permission"
    __table_args__ = (UniqueConstraint("role_key", "perm_key", name="uq_role_perm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(32), ForeignKey("sys_role.key"), index=True)
    perm_key: Mapped[str] = mapped_column(String(64), ForeignKey("sys_permission.key"), index=True)


class Menu(Base):
    __tablename__ = "sys_menu"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(128), default="")
    icon: Mapped[str] = mapped_column(String(64), default="")
    permission: Mapped[str] = mapped_column(String(64), default="")
    parent_key: Mapped[str] = mapped_column(String(64), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(64))
    role_key: Mapped[str] = mapped_column(String(32), ForeignKey("sys_role.key"))
    org: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Variety(Base):
    __tablename__ = "dim_variety"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(16), default="元/公斤")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Region(Base):
    __tablename__ = "dim_region"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16), default="省级")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Market(Base):
    __tablename__ = "dim_market"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    region_code: Mapped[str] = mapped_column(String(32), ForeignKey("dim_region.code"), index=True)
    market_type: Mapped[str] = mapped_column(String(16), default="批发")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class DataSource(Base):
    __tablename__ = "dim_data_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32), default="平台接口")
    protocol: Mapped[str] = mapped_column(String(64), default="REST")
    owner: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="正常")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PriceRecord(Base):
    __tablename__ = "price_record"
    __table_args__ = (
        Index("ix_price_series", "variety_id", "region_id", "market_type", "price_date"),
        UniqueConstraint("variety_id", "market_id", "price_date", "market_type", name="uq_price_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"), index=True)
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"), index=True)
    market_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_market.id"), index=True)
    market_type: Mapped[str] = mapped_column(String(16), default="批发")
    price_date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[float] = mapped_column(Float)
    min_price: Mapped[float] = mapped_column(Float, default=0)
    max_price: Mapped[float] = mapped_column(Float, default=0)
    volume: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(16), default="元/公斤")
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_data_source.id"), default=1)
    quality_flag: Mapped[str] = mapped_column(String(16), default="正常")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class FeatureRecord(Base):
    __tablename__ = "feature_record"
    __table_args__ = (Index("ix_feature_series", "variety_id", "region_id", "calc_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"))
    calc_date: Mapped[date] = mapped_column(Date)
    yoy_pct: Mapped[float] = mapped_column(Float, default=0)
    mom_pct: Mapped[float] = mapped_column(Float, default=0)
    volatility_30d: Mapped[float] = mapped_column(Float, default=0)
    seasonal_index: Mapped[float] = mapped_column(Float, default=100)
    cost_index: Mapped[float] = mapped_column(Float, default=100)
    freight_index: Mapped[float] = mapped_column(Float, default=100)
    weather_score: Mapped[float] = mapped_column(Float, default=100)
    futures_price: Mapped[float] = mapped_column(Float, default=0)
    holiday_flag: Mapped[int] = mapped_column(Integer, default=0)


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(64))
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"), index=True)
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"), index=True)
    granularity: Mapped[str] = mapped_column(String(16), default="day")
    version: Mapped[str] = mapped_column(String(16), default="v1")
    status: Mapped[str] = mapped_column(String(16), default="已训练")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    mape: Mapped[float] = mapped_column(Float, default=0)
    rmse: Mapped[float] = mapped_column(Float, default=0)
    direction_acc: Mapped[float] = mapped_column(Float, default=0)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[str] = mapped_column(Text, default="{}")
    artifact_path: Mapped[str] = mapped_column(String(255), default="")
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ForecastResult(Base):
    __tablename__ = "forecast_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_version.id"), index=True)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"), index=True)
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"), index=True)
    granularity: Mapped[str] = mapped_column(String(16), default="day")
    horizon: Mapped[int] = mapped_column(Integer, default=14)
    forecast_date: Mapped[date] = mapped_column(Date)
    target_date: Mapped[date] = mapped_column(Date)
    point: Mapped[float] = mapped_column(Float)
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    direction: Mapped[str] = mapped_column(String(8), default="持平")
    expected_change_pct: Mapped[float] = mapped_column(Float, default=0)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    explain: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ForecastBatch(Base):
    __tablename__ = "forecast_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    variety_ids: Mapped[str] = mapped_column(String(255), default="")
    region_ids: Mapped[str] = mapped_column(String(255), default="")
    horizon: Mapped[int] = mapped_column(Integer, default=14)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="已完成")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ForecastBatchItem(Base):
    __tablename__ = "forecast_batch_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("forecast_batch.id"), index=True)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"))
    point: Mapped[float] = mapped_column(Float, default=0)
    lower: Mapped[float] = mapped_column(Float, default=0)
    upper: Mapped[float] = mapped_column(Float, default=0)
    direction: Mapped[str] = mapped_column(String(8), default="持平")
    mape: Mapped[float] = mapped_column(Float, default=0)


class BacktestRecord(Base):
    __tablename__ = "backtest_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_version.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    actual: Mapped[float] = mapped_column(Float)
    predicted: Mapped[float] = mapped_column(Float)
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)


class AlertRule(Base):
    __tablename__ = "alert_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"), index=True)
    region_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("dim_region.id"), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(16), default="gt")
    threshold: Mapped[float] = mapped_column(Float, default=0)
    window_days: Mapped[int] = mapped_column(Integer, default=7)
    level: Mapped[str] = mapped_column(String(8), default="中")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channel: Mapped[str] = mapped_column(String(64), default="站内消息")
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AlertRecord(Base):
    __tablename__ = "alert_record"
    __table_args__ = (Index("ix_alert_status", "status", "level", "alert_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("alert_rule.id"), index=True)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"))
    alert_date: Mapped[date] = mapped_column(Date, index=True)
    level: Mapped[str] = mapped_column(String(8), default="中")
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="待处理")
    handler: Mapped[str] = mapped_column(String(64), default="")
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handle_note: Mapped[str] = mapped_column(Text, default="")
    notify_channel: Mapped[str] = mapped_column(String(64), default="站内消息")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScenarioSim(Base):
    __tablename__ = "scenario_sim"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    scenario_type: Mapped[str] = mapped_column(String(32))
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"))
    horizon: Mapped[int] = mapped_column(Integer, default=14)
    shock: Mapped[str] = mapped_column(Text, default="{}")
    price_change_pct: Mapped[float] = mapped_column(Float, default=0)
    price_range: Mapped[str] = mapped_column(Text, default="{}")
    risk_level: Mapped[str] = mapped_column(String(8), default="低")
    chart: Mapped[str] = mapped_column(Text, default="{}")
    factors: Mapped[str] = mapped_column(Text, default="[]")
    advice: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Report(Base):
    __tablename__ = "report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    report_type: Mapped[str] = mapped_column(String(16))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    variety_ids: Mapped[str] = mapped_column(String(255), default="")
    region_ids: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="已生成")
    summary: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    file_path: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ImportTask(Base):
    __tablename__ = "import_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_data_source.id"), default=1)
    filename: Mapped[str] = mapped_column(String(255), default="")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="已完成")
    errors: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QualityIssue(Base):
    __tablename__ = "quality_issue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price_id: Mapped[int] = mapped_column(Integer, ForeignKey("price_record.id"), default=0)
    variety_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("dim_region.id"))
    issue_date: Mapped[date] = mapped_column(Date)
    issue_type: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="待处理")
    resolved_by: Mapped[str] = mapped_column(String(64), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ScheduledTask(Base):
    __tablename__ = "scheduled_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    cron: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="启用")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str] = mapped_column(String(255), default="")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    module: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Notification(Base):
    """站内通知：预警产生/处置、导入完成、报告生成、任务执行等事件的闭环提醒。"""

    __tablename__ = "sys_notification"
    __table_args__ = (
        Index("ix_notify_user_time", "user_id", "created_at"),
        Index("ix_notify_read", "read_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0)
    username: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(32), default="系统")
    level: Mapped[str] = mapped_column(String(8), default="中")
    link: Mapped[str] = mapped_column(String(128), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class OpenApiClient(Base):
    """开放 API 调用方：密钥、限流配置与累计调用统计。"""

    __tablename__ = "open_api_client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    client_key: Mapped[str] = mapped_column(String(64), unique=True)
    secret: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit: Mapped[int] = mapped_column(Integer, default=60)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class OpenApiCall(Base):
    """开放 API 调用流水（按需保留近 7 天，用于调用量与耗时统计）。"""

    __tablename__ = "open_api_call"
    __table_args__ = (Index("ix_open_call_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(128), default="")
    method: Mapped[str] = mapped_column(String(8), default="GET")
    status: Mapped[int] = mapped_column(Integer, default=200)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ScheduledTaskRun(Base):
    """调度任务运行史：定时/手动每次执行的耗时、结果与异常，供任务看板与排查使用。"""

    __tablename__ = "scheduled_task_run"
    __table_args__ = (
        Index("ix_task_run_time", "started_at"),
        Index("ix_task_run_task", "task_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("scheduled_task.id"))
    task_key: Mapped[str] = mapped_column(String(64), default="")
    task_name: Mapped[str] = mapped_column(String(128), default="")
    trigger: Mapped[str] = mapped_column(String(8), default="手动")
    status: Mapped[str] = mapped_column(String(8), default="成功")
    result: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelRun(Base):
    """模型训练实验记录：一次训练的参数、回测指标与产物，支撑版本对比与重训追溯。"""

    __tablename__ = "model_run"
    __table_args__ = (
        Index("ix_model_run_time", "created_at"),
        Index("ix_model_run_pair", "variety_id", "region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), default=0)
    key: Mapped[str] = mapped_column(String(32), default="")
    name: Mapped[str] = mapped_column(String(128), default="")
    algorithm: Mapped[str] = mapped_column(String(32), default="")
    variety_id: Mapped[int] = mapped_column(ForeignKey("dim_variety.id"))
    region_id: Mapped[int] = mapped_column(ForeignKey("dim_region.id"))
    version: Mapped[str] = mapped_column(String(32), default="")
    trigger: Mapped[str] = mapped_column(String(8), default="手动")
    status: Mapped[str] = mapped_column(String(8), default="成功")
    params: Mapped[str] = mapped_column(Text, default="{}")
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    rows: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    artifact_key: Mapped[str] = mapped_column(String(255), default="")
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class EmailLog(Base):
    """邮件通道发送记录：监控页展示发送状态，失败原因便于排查（本地 Mailpit 收信）。"""

    __tablename__ = "sys_email_log"
    __table_args__ = (Index("ix_email_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    to_addr: Mapped[str] = mapped_column(String(128), default="")
    subject: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(32), default="系统")
    status: Mapped[str] = mapped_column(String(8), default="已发送")
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
