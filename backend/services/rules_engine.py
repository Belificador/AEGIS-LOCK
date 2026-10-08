"""Deterministic safety rules for incoming building telemetry."""

from typing import Any

from backend.config import get_settings
from backend.models.schemas import TelemetryEvent


def evaluate_event(event: TelemetryEvent) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if event.temperature_c is not None and event.temperature_c > 38:
        alerts.append(_alert("critical", "HIGH_TEMPERATURE", f"Temperatura crítica: {event.temperature_c:.1f} °C"))
    if event.voltage_v is not None and event.voltage_v == 0:
        alerts.append(_alert("critical", "POWER_LOSS", "Se detectó una lectura de 0 V"))
    if event.intrusion:
        alerts.append(_alert("critical", "INTRUSION", "Intrusión detectada"))
    if event.lockdown:
        alerts.append(_alert("lockdown", "LOCKDOWN", "El emisor reporta modo Lockdown activo"))
    return alerts


async def evaluate_voltage_fluctuation(
    event: TelemetryEvent,
    *,
    pool: Any,
    zone: str = "GLOBAL",
) -> dict[str, str] | None:
    """Report a voltage excursion once it crosses the configured consecutive-sample threshold."""
    voltage = event.voltage_v
    settings = get_settings()
    if voltage is None or voltage == 0 or settings.voltage_normal_min_v <= voltage <= settings.voltage_normal_max_v:
        return None
    if pool is None:
        return None

    band = "low" if voltage < settings.voltage_normal_min_v else "high"
    zone = str(zone or "GLOBAL")
    previous_samples = await pool.fetch(
        """
        SELECT (event->>'voltage_v')::double precision AS voltage_v
        FROM security_events
        WHERE source_id = $1
          AND coalesce(event->>'zona', event->>'zone', 'GLOBAL') = $2
          AND jsonb_typeof(event->'voltage_v') = 'number'
        ORDER BY received_at DESC
        LIMIT $3
        """,
        event.source_id,
        zone,
        settings.voltage_fluctuation_samples,
    )

    consecutive = 1
    for row in previous_samples:
        previous = float(row["voltage_v"])
        previous_band = (
            "low" if 0 < previous < settings.voltage_normal_min_v
            else "high" if previous > settings.voltage_normal_max_v
            else None
        )
        if previous_band != band:
            break
        consecutive += 1
    if consecutive < settings.voltage_fluctuation_samples:
        return None

    return _alert(
        "warning",
        "VOLTAGE_FLUCTUATION",
        f"Fluctuación de voltaje: {voltage:.1f} V fuera del rango normal "
        f"{settings.voltage_normal_min_v:g}–{settings.voltage_normal_max_v:g} V en {zone}",
    )


def _alert(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}
