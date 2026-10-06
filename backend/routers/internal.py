"""Server-to-server diagnostics ingress from the Render gemelo service."""

import hmac

from fastapi import APIRouter, HTTPException, Request

from backend.config import get_settings
from backend.models.schemas import ServiceErrorRequest
from backend.services.postgres_client import postgres_service

router = APIRouter(prefix="/internal", tags=["internal service"])


@router.post("/errors")
async def receive_service_error(payload: ServiceErrorRequest, request: Request) -> dict[str, bool]:
    settings = get_settings()
    authorization = request.headers.get("authorization", "")
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    expected = settings.telemetry_api_key or ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Servicio no autorizado")
    await postgres_service.write_error_log(
        error_type=payload.error_type,
        description=payload.description,
        duration_ms=payload.duration_ms,
    )
    return {"stored": postgres_service.pool is not None}
