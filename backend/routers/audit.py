"""Controlled audit events initiated by authenticated Dashboard operators."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter

from backend.core.dependencies import require_operator
from backend.core.rate_limit import limiter
from backend.models.schemas import AuditActionRequest
from backend.services.postgres_client import postgres_service

router = APIRouter(prefix="/audit", tags=["audit"])
_FORBIDDEN_DETAIL_KEYS = {"pin", "pin_code", "password", "token", "secret", "entered"}


@router.post("")
@limiter.limit("60/minute")
async def record_action(
    payload: AuditActionRequest,
    request: Request,
    claims: Annotated[dict[str, Any], Depends(require_operator)],
) -> dict[str, Any]:
    if len(payload.details) > 12:
        raise HTTPException(status_code=422, detail="Demasiados campos de auditoría")
    if any(key.casefold() in _FORBIDDEN_DETAIL_KEYS for key in payload.details):
        raise HTTPException(status_code=422, detail="La auditoría no admite secretos")
    row_id = await postgres_service.write_audit_log(
        action=payload.action.value,
        performed_by=str(claims["sub"]),
        details=payload.details,
    )
    return {"ok": True, "id": row_id}
