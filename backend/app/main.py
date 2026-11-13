"""FastAPI 应用入口：中间件、统一响应、异常处理、路由装配、前端静态托管。"""
from __future__ import annotations

import time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, BASE_DIR, MAIL_ENABLED, MAIL_HOST, MAIL_PORT, SCHEDULER_ENABLED
from .database import Base, SessionLocal, engine
from .logging_setup import log_event, set_request_id
from .security import ApiError

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from . import scheduler
    from .seed import ensure_initialized

    Base.metadata.create_all(bind=engine)
    ensure_initialized()
    scheduler.start()
    log_event("info", "app.start", version=APP_VERSION, scheduler=SCHEDULER_ENABLED)
    try:
        yield
    finally:
        scheduler.stop()
        log_event("info", "app.stop")


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
    request_id = f"{int(started * 1000) % 1000000:06d}-{id(request) % 100000:05d}"
    set_request_id(request_id)
    path = request.url.path
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.time() - started) * 1000
        log_event("error", "request.exception", method=request.method, path=path, elapsed_ms=round(elapsed, 1))
        raise
    elapsed = (time.time() - started) * 1000
    response.headers["X-Request-Id"] = request_id
    if path.startswith("/api/"):
        cache_state = response.headers.get("x-cache")
        try:
            from .services import metrics

            metrics.record_request(request.method, path, response.status_code, elapsed, cache_state)
        except Exception:  # 指标失败不影响请求
            pass
        if path != "/api/health":
            log_event(
                "info",
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                elapsed_ms=round(elapsed, 1),
                cache=cache_state or "",
            )
            if elapsed > 800:
                log_event("warn", "request.slow", method=request.method, path=path, elapsed_ms=round(elapsed, 1))
    return response


def _include_routers() -> None:
    import importlib

    for name in (
        "auth",
        "meta",
        "dashboard",
        "prices",
        "forecast",
        "model_mgmt",
        "alerts",
        "scenarios",
        "reports",
        "data_gov",
        "admin",
        "notifications",
        "observability",
        "open_api",
    ):
        try:
            module = importlib.import_module(f".routers.{name}", package=__package__)
        except ModuleNotFoundError:  # 可选路由尚未交付时跳过，保证服务可启动
            continue
        app.include_router(module.router, prefix="/api")


_include_routers()


@app.get("/api/health")
def health():
    from . import scheduler, storage
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
    try:
        storage_state = storage.health()
    except Exception as exc:  # pragma: no cover
        storage_state = {"configured": "", "backend": "fs", "ok": False, "degraded": True, "error": str(exc)}
    mail_state = {
        "enabled": MAIL_ENABLED,
        "endpoint": f"{MAIL_HOST}:{MAIL_PORT}",
        "web_ui": "http://127.0.0.1:8025" if MAIL_ENABLED else "",
    }
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "db": "ok" if db_ok else "error",
        "cache": "ok" if cache_ok else "error",
        "storage": "ok" if (storage_state.get("ok") and not storage_state.get("degraded")) else "degraded",
        "storage_backend": storage_state.get("backend", "fs"),
        "scheduler": "ok" if scheduler.status().get("running") else "paused",
        "mail": "ok" if MAIL_ENABLED else "paused",
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
