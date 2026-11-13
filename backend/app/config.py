"""全局配置：路径、端口、数据源（MySQL + Redis）与鉴权参数。

数据库与缓存均可通过环境变量切换，便于：
- 默认使用本地 Docker 中的 MySQL 8 与 Redis 7（生产化栈）；
- 无容器环境下用 ``AGRI_DB_BACKEND=sqlite`` 回退到单文件 SQLite；
- 联网受限环境用 ``AGRI_CACHE_ENABLED=0`` 关闭缓存。
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BASE_DIR / "data"
RUNTIME_DIR = BASE_DIR / ".runtime"
ARTIFACT_DIR = RUNTIME_DIR / "artifacts"
MODEL_DIR = ARTIFACT_DIR / "models"
REPORT_DIR = DATA_DIR / "reports"
UPLOAD_DIR = RUNTIME_DIR / "uploads"

for _p in (DATA_DIR, RUNTIME_DIR, ARTIFACT_DIR, MODEL_DIR, REPORT_DIR, UPLOAD_DIR):
    _p.mkdir(parents=True, exist_ok=True)

APP_NAME = "农产品价格预测分析系统"
APP_VERSION = "1.0.0"

HOST = os.getenv("AGRI_HOST", "127.0.0.1")
PORT = int(os.getenv("AGRI_PORT", "8017"))

# ---------------------------------------------------------------- 数据库
# mysql（默认，本地 Docker）| sqlite（无容器回退）
DB_BACKEND = os.getenv("AGRI_DB_BACKEND", "mysql").strip().lower()

MYSQL_HOST = os.getenv("AGRI_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("AGRI_MYSQL_PORT", "13306"))
MYSQL_DATABASE = os.getenv("AGRI_MYSQL_DATABASE", "agri_price")
MYSQL_USER = os.getenv("AGRI_MYSQL_USER", "agri")
MYSQL_PASSWORD = os.getenv("AGRI_MYSQL_PASSWORD", "Agri_2026")

DB_PATH = Path(os.getenv("AGRI_DB_PATH", str(RUNTIME_DIR / "agri.db")))
SQLITE_URL = f"sqlite:///{DB_PATH.as_posix()}"

_MYSQL_URL = (
    f"mysql+pymysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
)
DATABASE_URL = os.getenv("AGRI_DATABASE_URL") or (
    _MYSQL_URL if DB_BACKEND != "sqlite" else SQLITE_URL
)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

# ---------------------------------------------------------------- 缓存
REDIS_URL = os.getenv("AGRI_REDIS_URL", "redis://:DataSec_2026@127.0.0.1:16379/0")
CACHE_ENABLED = os.getenv("AGRI_CACHE_ENABLED", "1") not in {"0", "false", "False", "no"}
CACHE_PREFIX = os.getenv("AGRI_CACHE_PREFIX", "agri")
# 默认缓存时长（秒）：驾驶舱汇总、字典、价格序列、模型性能
CACHE_TTL_DASHBOARD = int(os.getenv("AGRI_CACHE_TTL_DASHBOARD", "30"))
CACHE_TTL_DICT = int(os.getenv("AGRI_CACHE_TTL_DICT", "300"))
CACHE_TTL_SERIES = int(os.getenv("AGRI_CACHE_TTL_SERIES", "60"))
CACHE_TTL_PERFORMANCE = int(os.getenv("AGRI_CACHE_TTL_PERFORMANCE", "120"))

SECRET_KEY = os.getenv("AGRI_SECRET_KEY", "agri-price-platform-local-secret-2026")
TOKEN_EXPIRE_MINUTES = int(os.getenv("AGRI_TOKEN_EXPIRE_MINUTES", "720"))
TOKEN_ISSUER = "agri-price-platform"

# ---------------------------------------------------------------- 增强能力
# 开放 API：未单独配置的调用方默认每分钟限流次数、调用流水保留天数
OPEN_API_RATE_LIMIT = int(os.getenv("AGRI_OPEN_API_RATE_LIMIT", "60"))
OPEN_API_CALL_RETENTION_DAYS = int(os.getenv("AGRI_OPEN_API_CALL_RETENTION_DAYS", "7"))
# 模型漂移监控：PSI 分箱数、判定阈值（<watch 平稳，<drift 关注，否则漂移）
DRIFT_BINS = int(os.getenv("AGRI_DRIFT_BINS", "10"))
DRIFT_PSI_WATCH = float(os.getenv("AGRI_DRIFT_PSI_WATCH", "0.1"))
DRIFT_PSI_DRIFT = float(os.getenv("AGRI_DRIFT_PSI_DRIFT", "0.25"))
DRIFT_WINDOW_DAYS = int(os.getenv("AGRI_DRIFT_WINDOW_DAYS", "90"))
DRIFT_BASELINE_DAYS = int(os.getenv("AGRI_DRIFT_BASELINE_DAYS", "180"))
# 预警处置时效：SLA 目标小时数（超时计为逾期）
ALERT_SLA_HOURS = int(os.getenv("AGRI_ALERT_SLA_HOURS", "24"))
# 站内通知保留天数
NOTIFICATION_RETENTION_DAYS = int(os.getenv("AGRI_NOTIFICATION_RETENTION_DAYS", "90"))

# ---------------------------------------------------------------- M3 基础设施
# 对象存储：minio（本地 Docker，S3 兼容，默认）| fs（本地目录降级）
STORAGE_BACKEND = os.getenv("AGRI_STORAGE", "minio").strip().lower()
STORAGE_ROOT = Path(os.getenv("AGRI_STORAGE_ROOT", str(RUNTIME_DIR / "storage")))
STORAGE_BUCKET = os.getenv("AGRI_STORAGE_BUCKET", "agri-artifacts")
MINIO_ENDPOINT = os.getenv("AGRI_MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("AGRI_MINIO_ACCESS_KEY", "agri")
MINIO_SECRET_KEY = os.getenv("AGRI_MINIO_SECRET_KEY", "Agri_2026_minio")
MINIO_SECURE = os.getenv("AGRI_MINIO_SECURE", "0") in {"1", "true", "True", "yes"}

# 调度器：进程内 cron 触发，默认开启；门禁/脚本可用 AGRI_SCHEDULER=0 关闭
SCHEDULER_ENABLED = os.getenv("AGRI_SCHEDULER", "1") not in {"0", "false", "False", "no"}
SCHEDULER_TICK_SECONDS = int(os.getenv("AGRI_SCHEDULER_TICK", "30"))
TASK_RUN_RETENTION_DAYS = int(os.getenv("AGRI_TASK_RUN_RETENTION_DAYS", "30"))

# 邮件通道：本地 Mailpit（SMTP 1025 / Web 8025），发送失败只记日志不影响主流程
MAIL_ENABLED = os.getenv("AGRI_MAIL_ENABLED", "1") not in {"0", "false", "False", "no"}
MAIL_HOST = os.getenv("AGRI_MAIL_HOST", "127.0.0.1")
MAIL_PORT = int(os.getenv("AGRI_MAIL_PORT", "1025"))
MAIL_FROM = os.getenv("AGRI_MAIL_FROM", "agri-platform@local")
MAIL_TO = os.getenv("AGRI_MAIL_TO", "admin@agri.local")
MAIL_ALERT_LEVELS = os.getenv("AGRI_MAIL_ALERT_LEVELS", "高")
MAIL_TIMEOUT = int(os.getenv("AGRI_MAIL_TIMEOUT", "5"))

# 可观测性：结构化访问日志与指标采样
LOG_DIR = RUNTIME_DIR / "logs"
LOG_FILE = LOG_DIR / "app.jsonl"
LOG_MAX_BYTES = int(os.getenv("AGRI_LOG_MAX_BYTES", str(8 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("AGRI_LOG_BACKUP_COUNT", "3"))
METRICS_ENABLED = os.getenv("AGRI_METRICS_ENABLED", "1") not in {"0", "false", "False", "no"}
METRICS_WINDOW_MINUTES = int(os.getenv("AGRI_METRICS_WINDOW_MINUTES", "60"))

# 备份输出目录
BACKUP_DIR = RUNTIME_DIR / "backups"

for _p in (STORAGE_ROOT, LOG_DIR, BACKUP_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# 默认管理员账号（首次启动时若库为空则自动初始化）
DEFAULT_ADMIN = ("admin", "Admin@2026")
