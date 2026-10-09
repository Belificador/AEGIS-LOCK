"""Admin-only diagnostics and audit data from Render PostgreSQL."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from backend.core.dependencies import require_admin
from backend.services.postgres_client import postgres_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/history")
async def history(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return await postgres_service.analytics_history(start=now - timedelta(days=days), end=now, limit=limit)


@router.get("/errors")
async def errors(
    _: Annotated[dict[str, Any], Depends(require_admin)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await postgres_service.error_history(limit=limit, offset=offset)
