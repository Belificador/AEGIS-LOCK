"""Translate simulator signal envelopes into validated AEGIS telemetry."""

from typing import Any
from uuid import uuid4

from backend.models.schemas import TelemetryEvent


_TEMPERATURE_TYPES = {"temperatura", "temperature"}
_VOLTAGE_TYPES = {"voltaje", "voltage"}
_OCCUPANCY_TYPES = {"aforo", "occupancy"}


def parse_telemetry(raw: dict[str, Any]) -> tuple[TelemetryEvent, dict[str, Any]]:
    """Validate either AEGIS's normalized schema or the simulator envelope."""
    if "tipo_evento" not in raw:
        event = TelemetryEvent.model_validate(raw)
        return event, event.model_dump(mode="json")

    event_type = str(raw.get("tipo_evento") or "telemetry").strip().lower()
    value = raw.get("valor")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    source_id = raw.get("source_id") or raw.get("origen")

    normalized: dict[str, Any] = {
        "event_id": raw.get("event_id") or uuid4(),
        "source_id": source_id,
        "event_type": event_type,
    }
    if raw.get("timestamp") is not None:
        normalized["timestamp"] = raw["timestamp"]

    if event_type in _TEMPERATURE_TYPES:
        normalized["temperature_c"] = _numeric_value(
            value, "temperature_c", "celsius", "lectura", "value", "valor"
        )
    elif event_type in _VOLTAGE_TYPES:
        normalized["voltage_v"] = _numeric_value(
            value, "voltage_v", "voltage", "v", "lectura", "value", "valor"
        )
        power_w = _optional_numeric(value, "power_w", "watts", "w") if isinstance(value, dict) else None
        if power_w is None:
            power_w = _optional_numeric(metadata, "power_w", "watts")
        power_kw = _optional_numeric(value, "power_kw") if isinstance(value, dict) else None
        if power_kw is None:
            power_kw = _optional_numeric(metadata, "power_kw")
        if power_w is not None:
            normalized["power_kw"] = power_w / 1000
        elif power_kw is not None:
            normalized["power_kw"] = power_kw
    elif event_type in _OCCUPANCY_TYPES:
        occupancy = _numeric_value(value, "count", "personas", "lectura", "value", "valor")
        if not occupancy.is_integer():
            raise ValueError("El aforo debe ser un entero")
        normalized["occupancy"] = int(occupancy)

    value_text = str(value).strip().upper() if value is not None and not isinstance(value, dict) else ""
    normalized["intrusion"] = _as_bool(raw.get("intrusion")) or (
        event_type in {"acceso_pin", "access_pin"} and value_text in {"DENIED", "LOCKOUT"}
    )
    normalized["lockdown"] = _as_bool(raw.get("lockdown")) or (
        event_type == "lockdown" and value_text not in {"", "FALSE", "0", "OFF", "NORMAL"}
    )
    if raw.get("message") is not None:
        normalized["message"] = raw["message"]
    elif event_type not in _TEMPERATURE_TYPES | _VOLTAGE_TYPES | _OCCUPANCY_TYPES:
        normalized["message"] = value_text[:500] or None

    event = TelemetryEvent.model_validate(normalized)
    event_data = {**raw, **event.model_dump(mode="json")}
    event_data["metadata"] = metadata
    return event, event_data


def _numeric_value(value: Any, *keys: str) -> float:
    result = _optional_numeric(value, *keys)
    if result is None:
        raise ValueError("El evento requiere un valor numérico")
    return result


def _optional_numeric(value: Any, *keys: str) -> float | None:
    candidate = value
    if isinstance(value, dict):
        candidate = next((value[key] for key in keys if value.get(key) is not None), None)
    if candidate is None or isinstance(candidate, bool):
        return None
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "si", "sí", "active", "activo"}
    return False
