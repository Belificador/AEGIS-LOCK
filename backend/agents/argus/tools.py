"""Strictly validated, allow-listed tools available to Argus."""

import json
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from backend.agents.argus.reporting import get_activity_summary, get_current_status
from backend.models.schemas import PinGenerateRequest, StrictModel
from backend.services.argus_reporting import get_recent_activity
from backend.services.camera_catalog import CAMERA_BY_ID
from backend.services.camera_checks import verify_camera_feed
from backend.services.temporary_pins import generate_temporary_pin


class SummaryArguments(StrictModel):
    days: int = Field(default=1, ge=1, le=7, strict=True)


class ActivityArguments(StrictModel):
    limit: int = Field(default=12, ge=1, le=20, strict=True)


class CameraArguments(StrictModel):
    camera_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class TelegramReportArguments(StrictModel):
    days: int = Field(default=1, ge=1, le=7, strict=True)


class PinRevokeArguments(StrictModel):
    pin_id: UUID | None = None
    door_name: str | None = Field(default=None, min_length=2, max_length=80)
    target_user: str | None = Field(default=None, min_length=2, max_length=120)

    @model_validator(mode="after")
    def validate_pin_selector(self) -> "PinRevokeArguments":
        if self.pin_id is not None:
            if self.door_name is not None or self.target_user is not None:
                raise ValueError("Usa el ID del PIN o la puerta y el nombre asignado, no ambos")
        elif not self.door_name or not self.target_user:
            raise ValueError("Indica el ID del PIN o una puerta y el nombre asignado")
        return self


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_building_status",
            "description": "Consulta un resumen reciente del estado del edificio.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_activity",
            "description": "Lee la actividad reciente como etiquetas seguras, sin payloads JSON ni datos personales.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                "required": ["limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_summary",
            "description": "Consulta métricas agregadas de AEGIS para los últimos días.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 7}},
                "required": ["days"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_camera",
            "description": "Comprueba una cámara del catálogo sin revelar su URL firmada.",
            "parameters": {
                "type": "object",
                "properties": {"camera_id": {"type": "string", "enum": sorted(CAMERA_BY_ID)}},
                "required": ["camera_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_temporary_pin",
            "description": "Genera un PIN temporal para una puerta catalogada. Solo para Administrador y ante una petición explícita.",
            "parameters": {
                "type": "object",
                "properties": {
                    "door_name": {"type": "string", "minLength": 2, "maxLength": 80},
                    "target_user": {"type": "string", "minLength": 2, "maxLength": 120},
                    "duration_hours": {"type": "integer", "minimum": 1, "maximum": 720},
                },
                "required": ["door_name", "target_user", "duration_hours"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revoke_temporary_pin",
            "description": "Revoca un PIN temporal. Busca por puerta y nombre asignado; si hay varios, pide al Administrador que seleccione el ID. También acepta un ID exacto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pin_id": {"type": "string", "format": "uuid"},
                    "door_name": {"type": "string", "minLength": 2, "maxLength": 80},
                    "target_user": {"type": "string", "minLength": 2, "maxLength": 120},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_report_to_telegram",
            "description": "Envía un informe agregado al Telegram privado vinculado al Administrador. Solo cuando se lo pida explícitamente desde el dashboard.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 7}},
                "required": ["days"],
                "additionalProperties": False,
            },
        },
    },
]


def tools_for_role(
    role: str,
    *,
    channel: str | None = None,
    allow_temporary_pin: bool = False,
    allow_temporary_pin_revocation: bool = False,
    allow_telegram_report: bool = False,
) -> list[dict[str, Any]]:
    available = []
    for tool in TOOLS:
        name = tool["function"]["name"]
        if name == "generate_temporary_pin" and (
            role != "admin" or channel == "telegram" or not allow_temporary_pin
        ):
            continue
        if name == "revoke_temporary_pin" and (
            role != "admin" or channel == "telegram" or not allow_temporary_pin_revocation
        ):
            continue
        if name == "send_report_to_telegram" and (
            role != "admin" or channel == "telegram" or not allow_telegram_report
        ):
            continue
        available.append(tool)
    return available


async def run_tool(
    name: str,
    arguments_json: str,
    claims: dict[str, Any],
    *,
    allow_temporary_pin: bool = False,
    allow_temporary_pin_revocation: bool = False,
    allow_telegram_report: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        arguments = json.loads(arguments_json or "{}")
    except (ValueError, TypeError) as exc:
        raise ValueError("Los argumentos no son JSON válido") from exc
    if not isinstance(arguments, dict):
        raise ValueError("Los argumentos deben ser un objeto")

    if name == "get_building_status":
        if arguments:
            raise ValueError("Esta herramienta no acepta argumentos")
        return await get_current_status(), None
    if name == "get_recent_activity":
        request = ActivityArguments.model_validate(arguments)
        return {"activities": await get_recent_activity(request.limit)}, None
    if name == "get_activity_summary":
        request = SummaryArguments.model_validate(arguments)
        return await get_activity_summary(request.days), None
    if name == "verify_camera":
        request = CameraArguments.model_validate(arguments)
        if request.camera_id not in CAMERA_BY_ID:
            raise ValueError("Cámara fuera del catálogo permitido")
        return await verify_camera_feed(request.camera_id), None
    if name == "generate_temporary_pin":
        if (
            claims.get("role") != "admin"
            or claims.get("channel") == "telegram"
            or not allow_temporary_pin
        ):
            raise PermissionError("Solo un Administrador que pidió explícitamente el PIN desde AEGIS puede generarlo")
        request = PinGenerateRequest.model_validate(arguments)
        pin = await generate_temporary_pin(request, created_by=str(claims.get("sub", "admin")))
        public_result = {"created": True, "door_name": pin.door_name, "expires_at": pin.expires_at.isoformat()}
        private_result = {
            "pin_code": pin.pin_code,
            "target_user": pin.target_user,
            "door_name": pin.door_name,
            "expires_at": pin.expires_at.isoformat(),
        }
        return public_result, private_result
    if name == "revoke_temporary_pin":
        if (
            claims.get("role") != "admin"
            or claims.get("channel") == "telegram"
            or not allow_temporary_pin_revocation
        ):
            raise PermissionError("Solo un Administrador desde AEGIS puede revocar PINes temporales")
        request = PinRevokeArguments.model_validate(arguments)
        from backend.services.temporary_pins import revoke_temporary_pin

        return await revoke_temporary_pin(
            created_by=str(claims.get("sub", "admin")),
            pin_id=str(request.pin_id) if request.pin_id else None,
            door_name=request.door_name,
            target_user=request.target_user,
        ), None
    if name == "send_report_to_telegram":
        if claims.get("role") != "admin" or claims.get("channel") == "telegram" or not allow_telegram_report:
            raise PermissionError("El envío requiere una solicitud explícita de Administrador desde AEGIS")
        request = TelegramReportArguments.model_validate(arguments)
        from backend.agents.argus.agent import send_on_demand_report

        return await send_on_demand_report(request.days, claims), None
    raise ValueError("Herramienta no permitida")
