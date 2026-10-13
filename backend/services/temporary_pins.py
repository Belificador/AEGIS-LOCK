"""Reusable, audited PIN creation shared by the Admin API and Argus."""

from datetime import datetime, timedelta, timezone
import secrets
from uuid import UUID, uuid4

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
    stored = None
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.duration_hours)
    for _ in range(100):
        pin_code = str(secrets.randbelow(10 ** settings.pin_code_length)).zfill(settings.pin_code_length)
        pin_digest = hash_pin(str(door["door_name"]), pin_code)
        stored = await postgres_service.create_temporary_pin_if_hash_available(
            pin_id=str(uuid4()),
            door_name=str(door["door_name"]),
            pin_code=encrypt_pin(str(door["door_name"]), pin_code),
            pin_hash=pin_digest,
            target_user=payload.target_user,
            created_by=created_by,
            expires_at=expires_at,
        )
        if stored is not None:
            break
    else:
        raise HTTPException(status_code=503, detail="No se pudo generar un PIN disponible")

    return PinGenerateResponse(
        id=stored["id"],
        door_name=stored["door_name"],
        pin_code=pin_code,
        target_user=stored["target_user"],
        created_by=stored["created_by"],
        expires_at=stored["expires_at"],
        is_active=stored["is_active"],
    )


async def revoke_temporary_pin(
    *,
    created_by: str,
    pin_id: str | None = None,
    door_name: str | None = None,
    target_user: str | None = None,
) -> dict[str, object]:
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está disponible")

    if pin_id:
        try:
            selected_id = str(UUID(pin_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("El ID del PIN no es válido") from exc
        revoked = await postgres_service.deactivate_temporary_pin_and_audit(
            selected_id, performed_by=created_by
        )
        if revoked is None:
            return {"revoked": False, "reason": "not_found"}
    else:
        door = canonical_door(door_name or "")
        if door is None or not target_user or not target_user.strip():
            raise ValueError("Argus necesita una puerta y el nombre asignado para buscar el PIN")
        matches = [
            pin for pin in await postgres_service.list_temporary_pins(limit=200)
            if pin["door_name"] == door["door_name"]
            and str(pin["target_user"]).strip().casefold() == target_user.strip().casefold()
        ]
        if not matches:
            return {"revoked": False, "reason": "not_found"}
        if len(matches) > 1:
            return {
                "revoked": False,
                "ambiguous": True,
                "matches": [
                    {"pin_id": pin["id"], "expires_at": pin["expires_at"].isoformat()}
                    for pin in matches[:10]
                ],
            }
        revoked = await postgres_service.deactivate_temporary_pin_and_audit(
            str(matches[0]["id"]), performed_by=created_by
        )
        if revoked is None:
            return {"revoked": False, "reason": "not_found"}

    return {
        "revoked": True,
        "pin_id": revoked["id"],
        "door_name": revoked["door_name"],
        "expires_at": revoked["expires_at"].isoformat(),
    }
