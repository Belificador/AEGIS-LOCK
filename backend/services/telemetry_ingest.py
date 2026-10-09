"""Translate simulator signal envelopes into validated AEGIS telemetry."""

import math
from typing import Any
from uuid import uuid4

from backend.models.schemas import TelemetryEnvelope, TelemetryEvent


_TEMPERATURE_TYPES = {"temperatura", "temperature"}
_VOLTAGE_TYPES = {"voltaje", "voltage"}
_OCCUPANCY_TYPES = {"aforo", "occupancy"}


def parse_telemetry(raw: dict[str, Any]) -> tuple[TelemetryEvent, dict[str, Any]]:
    """Validate either AEGIS's normalized schema or the simulator envelope."""
    if "tipo_evento" not in raw:
        event = TelemetryEvent.model_validate(raw)
        return event, event.model_dump(mode="json")

    envelope_data = dict(raw)
    if isinstance(envelope_data.get("tipo_evento"), str):
        envelope_data["tipo_evento"] = envelope_data["tipo_evento"].strip().lower()
    if isinstance(envelope_data.get("event_type"), str):
        envelope_data["event_type"] = envelope_data["event_type"].strip().lower()
    envelope = TelemetryEnvelope.model_validate(envelope_data)
    event_type = envelope.tipo_evento
    value = envelope.valor
    metadata = envelope.metadata.model_dump(exclude_none=True)
    source_id = envelope.source_id or envelope.origen

    normalized: dict[str, Any] = {
        "event_id": envelope.event_id or uuid4(),
        "source_id": source_id,
        "event_type": event_type,
    }
    if envelope.timestamp is not None:
        normalized["timestamp"] = envelope.timestamp
    if envelope.energy_kwh is not None:
        normalized["energy_kwh"] = envelope.energy_kwh
    elif metadata.get("energy_kwh") is not None:
        normalized["energy_kwh"] = metadata["energy_kwh"]

    if event_type in _TEMPERATURE_TYPES:
        normalized["temperature_c"] = _numeric_value(
            value if value is not None else envelope.temperature_c,
            "temperature_c", "celsius", "lectura", "value", "valor",
        )
    elif event_type in _VOLTAGE_TYPES:
        normalized["voltage_v"] = _numeric_value(
            value if value is not None else envelope.voltage_v,
            "voltage_v", "voltage", "v", "lectura", "value", "valor",
        )
        power_w = _optional_numeric(value, "power_w", "watts", "w") if isinstance(value, dict) else None
        if power_w is None:
            power_w = _optional_numeric(metadata, "power_w", "watts")
        power_kw = _optional_numeric(value, "power_kw") if isinstance(value, dict) else None
        if power_kw is None:
            power_kw = envelope.power_kw if envelope.power_kw is not None else _optional_numeric(metadata, "power_kw")
        if power_w is not None:
            normalized["power_kw"] = power_w / 1000
        elif power_kw is not None:
            normalized["power_kw"] = power_kw
    elif event_type in _OCCUPANCY_TYPES and _is_current_occupancy(metadata):
        occupancy = _numeric_value(
            value if value is not None else envelope.occupancy,
            "count", "personas", "lectura", "value", "valor",
        )
        if not occupancy.is_integer():
            raise ValueError("El aforo debe ser un entero")
        normalized["occupancy"] = int(occupancy)

    value_text = str(value).strip().upper() if value is not None and not isinstance(value, dict) else ""
    normalized["intrusion"] = envelope.intrusion or (
        event_type in {"acceso_pin", "access_pin"} and value_text in {"DENIED", "LOCKOUT"}
    )
    normalized["lockdown"] = envelope.lockdown or (
        event_type == "lockdown" and value_text not in {"", "FALSE", "0", "OFF", "NORMAL"}
    )
    if envelope.message is not None:
        normalized["message"] = envelope.message
    elif event_type not in _TEMPERATURE_TYPES | _VOLTAGE_TYPES | _OCCUPANCY_TYPES:
        normalized["message"] = value_text[:500] or None

    event = TelemetryEvent.model_validate(normalized)
    event_data = event.model_dump(mode="json")
    event_data.update({
        "tipo_evento": event_type,
        "event_type": event_type,
        "origen": envelope.origen or source_id,
        "metadata": metadata,
    })
    if envelope.zona or envelope.zone:
        event_data["zona"] = envelope.zona or envelope.zone
        event_data["zone"] = envelope.zone or envelope.zona
    if value is not None:
        event_data["valor"] = value
    if envelope.camera_id is not None:
        event_data["camera_id"] = envelope.camera_id
    return event, event_data


def _is_current_occupancy(metadata: dict[str, Any]) -> bool:
    """Distinguish the current count from Gemelo's action events also typed aforo."""
    state_marker = metadata.get("estado_actual")
    if state_marker is not None:
        return state_marker is True
    return not any(metadata.get(field) is not None for field in ("accion", "motivo", "enviados", "withdrawals"))


def _numeric_value(value: Any, *keys: str) -> float:
    result = _optional_numeric(value, *keys)
    if result is None:
        raise ValueError("El evento requiere un valor numérico")
    return result


def _optional_numeric(value: Any, *keys: str) -> float | None:
    candidate = value
    if isinstance(value, dict):
        candidate = next((value[key] for key in keys if value.get(key) is not None), None)
    if candidate is None or isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
        return None
    number = float(candidate)
    return number if math.isfinite(number) else None
