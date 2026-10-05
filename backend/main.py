"""AEGIS LOCK local API entry point."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.config import get_settings
from backend.core.middleware import SecurityHeadersAndSizeLimitMiddleware
from backend.core.rate_limit import limiter
from backend.routers import ai_chat, auth, telemetry, ws_manager
from backend.services.supabase_client import supabase_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.latest_event = None
    await supabase_service.connect(settings.supabase_url, settings.supabase_key)
    yield
    await supabase_service.close()


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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
# Compatibility route for the HTML prototype's configurable REST login URL.
app.add_api_route("/api/login", auth.login, methods=["POST"], include_in_schema=False)
app.include_router(ai_chat.router, prefix=settings.api_v1_prefix)
app.include_router(ws_manager.router)
app.include_router(telemetry.router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "aegis-lock-api"}
