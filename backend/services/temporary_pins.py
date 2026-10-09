"""Reusable, audited PIN creation shared by the Admin API and Argus."""

from datetime import datetime, timedelta, timezone
import secrets
from uuid import uuid4

from fastapi import HTTPException

from backend.config import get_settings
from backend.core.pin_security import encrypt_pin, hash_pin
from backend.models.schemas import PinGenerateRequest, PinGenerateResponse
from backend.services.door_catalog import canonical_door
from backend.services.postgres_client import postgres_service


async def generate_temporary_pin(payload: PinGenerateRequest, *, created_by: str) -> PinGenerateResponse:
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está disponible")
    door = canonical_door(payload.door_name)
    if door is None:
        raise HTTPException(status_code=422, detail="La puerta no pertenece al catálogo del gemelo")

    settings = get_settings()
    pin_code = ""
    pin_digest = ""
    for _ in range(100):
        pin_code = str(secrets.randbelow(10 ** settings.pin_code_length)).zfill(settings.pin_code_length)
        pin_digest = hash_pin(str(door["door_name"]), pin_code)
        if not await postgres_service.temporary_pin_hash_exists(str(door["door_name"]), pin_digest):
            break
    else:
        raise HTTPException(status_code=503, detail="No se pudo generar un PIN disponible")

    stored = await postgres_service.create_temporary_pin(
        pin_id=str(uuid4()),
        door_name=str(door["door_name"]),
        pin_code=encrypt_pin(str(door["door_name"]), pin_code),
        pin_hash=pin_digest,
        target_user=payload.target_user,
        created_by=created_by,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.duration_hours),
    )
    await postgres_service.write_audit_log(
        action="PIN_GENERATED",
        performed_by=created_by,
        details={"pin_id": stored["id"], "door_name": stored["door_name"], "target_user": payload.target_user},
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
