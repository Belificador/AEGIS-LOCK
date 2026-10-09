"""AEGIS LOCK local API entry point."""

from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from backend.config import get_settings
from backend.core.middleware import SecurityHeadersAndSizeLimitMiddleware
from backend.core.rate_limit import WebSocketRateLimiter, limiter
from backend.routers import ai_chat, analytics, audit, auth, cameras, internal, pins, telemetry, telemetry_rest, telegram, ws_manager
from backend.services.postgres_client import postgres_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.latest_event = None
    app.state.telemetry_snapshot_bootstrapped = False
    app.state.websocket_rate_limiter = WebSocketRateLimiter(settings.rate_limit_storage_uri or "memory://")
    await ws_manager.manager.start(
        settings.rate_limit_storage_uri,
        app.state.websocket_rate_limiter,
        enable_pubsub=False,
    )
    try:
        await postgres_service.connect(
            settings.database_url,
            operator_password=settings.demo_operator_password,
            admin_password=settings.demo_admin_password,
        )
        yield
    finally:
        await telemetry.close_telemetry_persistence()
        await ws_manager.manager.close()
        await app.state.websocket_rate_limiter.close()
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
    response = await call_next(request)
    if response.status_code in {401, 403, 422}:
        client = request.client.host if request.client else "unknown"
        logging.getLogger("security.http").warning(
            "request_rejected status=%s method=%s path=%s client=%s",
            response.status_code,
            request.method,
            request.url.path,
            client[:80],
        )
    return response


app.state.limiter = limiter


async def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> Response:
    client = request.client.host if request.client else "unknown"
    logging.getLogger("security.rate_limit").warning(
        "rate_limit_exceeded method=%s path=%s client=%s",
        request.method,
        request.url.path,
        client[:80],
    )
    return await _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded)
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
app.include_router(telemetry_rest.router, prefix=settings.api_v1_prefix)


@app.exception_handler(StarletteHTTPException)
async def record_forbidden_request(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 403:
        try:
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description=f"{request.method} {request.url.path}",
                duration_ms=round((time.monotonic() - request.state.started_monotonic) * 1000)
                if hasattr(request.state, "started_monotonic") else None,
            )
        except Exception:
            logging.getLogger(__name__).exception("No se pudo guardar el 403 en error_logs")
    return await http_exception_handler(request, exc)


@app.get("/health", tags=["health"])
@limiter.limit("120/minute")
async def health(request: Request) -> JSONResponse:
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
