"""FastAPI 应用入口：中间件、统一响应、异常处理、路由装配、前端静态托管。"""
from __future__ import annotations

import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, BASE_DIR
from .database import Base, SessionLocal, engine
from .security import ApiError

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .seed import ensure_initialized

    Base.metadata.create_all(bind=engine)
    ensure_initialized()
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version=APP_VERSION,
    description="农产品价格预测分析系统后端服务：价格监测、预测建模、预警闭环、情景推演、报告与开放 API。",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5177", "http://localhost:5177", "http://127.0.0.1:4177"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"code": "E5000", "message": f"服务处理异常：{exc}", "data": None},
    )


@app.middleware("http")
async def access_middleware(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.url.path not in {"/api/health"}:
        elapsed = (time.time() - started) * 1000
        if elapsed > 800:
            print(f"[slow] {request.method} {request.url.path} {elapsed:.0f}ms")
    return response


def _include_routers() -> None:
    from .routers import (
        admin,
        alerts,
        auth,
        dashboard,
        data_gov,
        forecast,
        meta,
        model_mgmt,
        notifications,
        open_api,
        prices,
        reports,
        scenarios,
    )

    for module in (
        auth,
        meta,
        dashboard,
        prices,
        forecast,
        model_mgmt,
        alerts,
        scenarios,
        reports,
        data_gov,
        admin,
        notifications,
        open_api,
    ):
        app.include_router(module.router, prefix="/api")


_include_routers()


@app.get("/api/health")
def health():
    from .cache import cache_available
    from .database import SessionLocal
    from sqlalchemy import text

    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - 健康检查兜底
        db_ok = False
    try:
        cache_ok = cache_available()
    except Exception:  # pragma: no cover - 缓存探测兜底
        cache_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "db": "ok" if db_ok else "error",
        "cache": "ok" if cache_ok else "error",
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


# ---------------------- 前端静态资源（构建产物存在时） ----------------------

DIST_DIR = BASE_DIR / "frontend" / "dist"

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                {"code": "E4040", "message": "请求的接口不存在", "data": None}, status_code=404
            )
        target = DIST_DIR / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")
