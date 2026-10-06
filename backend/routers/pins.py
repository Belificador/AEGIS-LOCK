"""Admin PIN management and the authenticated gemelo validation endpoint."""

from datetime import datetime, timedelta, timezone
import hmac
import logging
import secrets
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.config import get_settings
from backend.core.dependencies import require_admin
from backend.core.pin_security import decrypt_pin, encrypt_pin, hash_pin
from backend.core.rate_limit import limiter
from backend.models.schemas import PinGenerateRequest, PinGenerateResponse, PinValidationRequest
from backend.services.door_catalog import DOORS, canonical_door
from backend.services.postgres_client import postgres_service

router = APIRouter(prefix="/pins", tags=["temporary pins"])
_logger = logging.getLogger(__name__)


@router.get("/doors")
async def list_doors(_: Annotated[dict[str, Any], Depends(require_admin)]) -> list[dict[str, Any]]:
    return [dict(door) for door in DOORS]


@router.post("/generate", response_model=PinGenerateResponse)
@limiter.limit("10/minute")
async def generate_pin(
    payload: PinGenerateRequest,
    request: Request,
    claims: Annotated[dict[str, Any], Depends(require_admin)],
) -> PinGenerateResponse:
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está disponible")
    door = canonical_door(payload.door_name)
    if door is None:
        raise HTTPException(status_code=422, detail="La puerta no pertenece al catálogo del gemelo")

    settings = get_settings()
    pin_code = ""
    pin_digest = ""
    for _ in range(100):
        pin_code = str(secrets.randbelow(10**settings.pin_code_length)).zfill(settings.pin_code_length)
        pin_digest = hash_pin(str(door["door_name"]), pin_code)
        if not await postgres_service.temporary_pin_hash_exists(str(door["door_name"]), pin_digest):
            break
    else:
        raise HTTPException(status_code=503, detail="No se pudo generar un PIN disponible")

    pin_id = str(uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.duration_hours)
    created_by = str(claims["sub"])
    stored = await postgres_service.create_temporary_pin(
        pin_id=pin_id,
        door_name=str(door["door_name"]),
        pin_code=encrypt_pin(str(door["door_name"]), pin_code),
        pin_hash=pin_digest,
        target_user=payload.target_user,
        created_by=created_by,
        expires_at=expires_at,
    )
    await postgres_service.write_audit_log(
        action="PIN_GENERATED",
        performed_by=created_by,
        details={"pin_id": pin_id, "door_name": stored["door_name"], "target_user": payload.target_user},
    )
    return PinGenerateResponse(
        id=stored["id"],
        door_name=stored["door_name"],
        pin_code=pin_code,
        target_user=stored["target_user"],
        created_by=stored["created_by"],
        expires_at=stored["expires_at"],
        is_active=stored["is_active"],
    )


@router.get("")
@limiter.limit("30/minute")
async def list_pins(
    request: Request,
    _: Annotated[dict[str, Any], Depends(require_admin)],
    include_inactive: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    pins = await postgres_service.list_temporary_pins(
        limit=max(1, min(limit, 200)), include_inactive=include_inactive
    )
    result = []
    for pin in pins:
        try:
            visible_pin = decrypt_pin(pin["door_name"], pin["pin_code"])
        except Exception:
            _logger.exception("No se pudo descifrar PIN temporal id=%s", pin["id"])
            visible_pin = None
        result.append({
            "id": pin["id"],
            "door_name": pin["door_name"],
            "pin_code": visible_pin,
            "target_user": pin["target_user"],
            "created_by": pin["created_by"],
            "expires_at": pin["expires_at"],
            "is_active": pin["is_active"] and pin["expires_at"] > datetime.now(timezone.utc),
            "created_at": pin["created_at"],
        })
    return result


@router.delete("/{pin_id}")
@limiter.limit("20/minute")
async def revoke_pin(
    pin_id: str,
    request: Request,
    claims: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    revoked = await postgres_service.deactivate_temporary_pin(pin_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="PIN temporal no encontrado o ya revocado")
    actor = str(claims["sub"])
    await postgres_service.write_audit_log(
        action="PIN_REVOKED",
        performed_by=actor,
        details={"pin_id": pin_id, "door_name": revoked["door_name"]},
    )
    return {"ok": True, "id": pin_id, "is_active": False}


@router.post("/validate")
@limiter.limit("30/minute")
async def validate_pin(payload: PinValidationRequest, request: Request) -> dict[str, Any]:
    settings = get_settings()
    authorization = request.headers.get("authorization", "")
    supplied_key = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    expected_key = settings.telemetry_api_key or ""
    if not expected_key or not hmac.compare_digest(supplied_key, expected_key):
        raise HTTPException(status_code=403, detail="Servicio del gemelo no autorizado")
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está disponible")

    door = canonical_door(payload.door_name)
    if door is None or len(payload.pin_code) != settings.pin_code_length:
        return {"valid": False}
    row = await postgres_service.validate_temporary_pin(
        str(door["door_name"]), hash_pin(str(door["door_name"]), payload.pin_code)
    )
    if row is None:
        return {"valid": False}
    await postgres_service.write_audit_log(
        action="PIN_VALIDATED",
        performed_by="gemelo-service",
        details={"pin_id": row["id"], "door_name": row["door_name"], "target_user": row["target_user"]},
    )
    return {"valid": True, "target_user": row["target_user"], "pin_id": row["id"]}
