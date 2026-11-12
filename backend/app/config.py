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

# 默认管理员账号（首次启动时若库为空则自动初始化）
DEFAULT_ADMIN = ("admin", "Admin@2026")
