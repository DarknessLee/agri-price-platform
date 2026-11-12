"""全局配置：路径、端口、鉴权参数。"""
from __future__ import annotations

import os
from pathlib import Path

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
DB_PATH = Path(os.getenv("AGRI_DB_PATH", str(RUNTIME_DIR / "agri.db")))
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

SECRET_KEY = os.getenv("AGRI_SECRET_KEY", "agri-price-platform-local-secret-2026")
TOKEN_EXPIRE_MINUTES = int(os.getenv("AGRI_TOKEN_EXPIRE_MINUTES", "720"))
TOKEN_ISSUER = "agri-price-platform"

# 默认管理员账号（首次启动时若库为空则自动初始化）
DEFAULT_ADMIN = ("admin", "Admin@2026")
