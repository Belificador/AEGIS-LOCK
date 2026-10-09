"""AEGIS LOCK local API entry point."""

from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.config import get_settings
from backend.core.middleware import SecurityHeadersAndSizeLimitMiddleware
from backend.core.rate_limit import limiter
from backend.routers import ai_chat, analytics, audit, auth, cameras, internal, pins, telemetry, telegram, ws_manager
from backend.services.postgres_client import postgres_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.latest_event = None
    await postgres_service.connect(
        settings.database_url,
        operator_password=settings.demo_operator_password,
        admin_password=settings.demo_admin_password,
    )
    try:
        yield
    finally:
        await postgres_service.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)
app.add_middleware(SecurityHeadersAndSizeLimitMiddleware, max_request_bytes=settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def measure_request_duration(request: Request, call_next):
    request.state.started_monotonic = time.monotonic()
    return await call_next(request)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
# Compatibility route for the HTML prototype's configurable REST login URL.
app.add_api_route("/api/login", auth.login, methods=["POST"], include_in_schema=False)
app.include_router(ai_chat.router, prefix=settings.api_v1_prefix)
app.include_router(pins.router, prefix=settings.api_v1_prefix)
app.include_router(analytics.router, prefix=settings.api_v1_prefix)
app.include_router(audit.router, prefix=settings.api_v1_prefix)
app.include_router(cameras.router, prefix=settings.api_v1_prefix)
app.include_router(internal.router, prefix=settings.api_v1_prefix)
app.include_router(telegram.router, prefix=settings.api_v1_prefix)
app.include_router(ws_manager.router)
app.include_router(telemetry.router)


@app.exception_handler(StarletteHTTPException)
async def record_forbidden_request(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 403:
        try:
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description=f"{request.method} {request.url.path}: {str(exc.detail)[:300]}",
                duration_ms=round((time.monotonic() - request.state.started_monotonic) * 1000)
                if hasattr(request.state, "started_monotonic") else None,
            )
        except Exception:
            logging.getLogger(__name__).exception("No se pudo guardar el 403 en error_logs")
    return await http_exception_handler(request, exc)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    if not await postgres_service.is_healthy():
        if settings.environment.lower() != "production" and not settings.database_url:
            return JSONResponse(
                content={"status": "ok", "service": "aegis-lock-api", "database": "not_configured"}
            )
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "service": "aegis-lock-api", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ok", "service": "aegis-lock-api", "database": "ok"})
