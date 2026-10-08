"""Typed, allowlisted functions Argus may request from AEGIS."""

import json
from typing import Any
from pydantic import Field

from backend.agents.argus.reporting import get_activity_summary, get_current_status
from backend.models.schemas import PinGenerateRequest, StrictModel
from backend.services.argus_reporting import get_recent_activity
from backend.services.argus_reporting import get_current_occupancy
from backend.services.camera_catalog import CAMERA_BY_ID
from backend.services.temporary_pins import generate_temporary_pin
from backend.services.camera_checks import verify_camera_feed


class SummaryArguments(StrictModel):
    days: int = Field(default=1, ge=1, le=7, strict=True)


class ActivityArguments(StrictModel):
    limit: int = Field(default=12, ge=1, le=20, strict=True)


class CameraArguments(StrictModel):
    camera_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class TelegramReportArguments(StrictModel):
    days: int = Field(default=1, ge=1, le=7, strict=True)


TOOLS = [
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
            "name": "get_current_occupancy",
            "description": "Consulta el aforo por zona con lecturas recientes. Si el aforo está desactualizado, indica que no puede confirmarse el total.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_activity",
            "description": "Lee la bitácora unificada de telemetría, alertas, auditoría y errores recientes, como resúmenes sin payloads ni datos personales.",
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
            "description": "Consulta métricas agregadas del edificio para los últimos días, sin nombres ni códigos PIN.",
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
            "description": "Comprueba el feed de una cámara catalogada sin revelar su URL firmada.",
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
            "name": "send_report_to_telegram",
            "description": "Envía un informe agregado de AEGIS al Telegram privado vinculado al Administrador que lo pidió. Úsala solo ante una solicitud explícita de enviar el informe a Telegram.",
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
            "name": "generate_temporary_pin",
            "description": "Genera un PIN temporal para una puerta catalogada. Solo para Administrador y ante una petición explícita del usuario.",
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
]


def tools_for_role(
    role: str,
    *,
    channel: str | None = None,
    allow_telegram_report: bool = False,
) -> list[dict[str, Any]]:
    available = []
    for tool in TOOLS:
        name = tool["function"]["name"]
        if name == "generate_temporary_pin" and (role != "admin" or channel == "telegram"):
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
    allow_telegram_report: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        arguments = json.loads(arguments_json or "{}")
    except (ValueError, TypeError) as exc:
        raise ValueError("Los argumentos de herramienta no son JSON válido") from exc
    if not isinstance(arguments, dict):
        raise ValueError("Los argumentos de herramienta deben ser un objeto")

    if name == "get_building_status":
        if arguments:
            raise ValueError("Esta herramienta no acepta argumentos")
        return await get_current_status(), None
    if name == "get_current_occupancy":
        if arguments:
            raise ValueError("Esta herramienta no acepta argumentos")
        return await get_current_occupancy(), None
    if name == "get_recent_activity":
        request = ActivityArguments.model_validate(arguments)
        return {"activities": await get_recent_activity(request.limit)}, None
    if name == "get_activity_summary":
        request = SummaryArguments.model_validate(arguments)
        return await get_activity_summary(request.days), None
    if name == "verify_camera":
        request = CameraArguments.model_validate(arguments)
        camera = CAMERA_BY_ID.get(request.camera_id)
        if camera is None:
            raise ValueError("Cámara fuera del catálogo permitido")
        return await verify_camera_feed(request.camera_id), None
    if name == "send_report_to_telegram":
        if claims.get("role") != "admin" or claims.get("channel") == "telegram" or not allow_telegram_report:
            raise PermissionError("Enviar informes a Telegram requiere una solicitud explícita desde el dashboard con perfil Administrador")
        request = TelegramReportArguments.model_validate(arguments)
        from backend.agents.argus.agent import send_on_demand_report

        return await send_on_demand_report(request.days, claims), None
    if name == "generate_temporary_pin":
        if claims.get("channel") == "telegram":
            raise PermissionError("La creación de PINes no está disponible desde Telegram")
        if claims.get("role") != "admin":
            raise PermissionError("La creación de PINes requiere perfil Administrador")
        request = PinGenerateRequest.model_validate(arguments)
        pin = await generate_temporary_pin(request, created_by=str(claims["sub"]))
        # No send PINs or visitor names back to OpenRouter.
        public_result = {"created": True, "door_name": pin.door_name, "expires_at": pin.expires_at.isoformat()}
        private_result = {
            "pin_code": pin.pin_code,
            "target_user": pin.target_user,
            "door_name": pin.door_name,
            "expires_at": pin.expires_at.isoformat(),
        }
        return public_result, private_result
    raise ValueError("Herramienta no permitida")
