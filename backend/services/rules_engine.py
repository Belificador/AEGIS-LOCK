"""Deterministic safety rules for incoming building telemetry."""

from typing import Any

from backend.models.schemas import TelemetryEvent

VOLTAGE_NORMAL_MIN_V = 110
VOLTAGE_NORMAL_MAX_V = 220


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
    """Report the transition into a real, explicit reading outside the normal voltage band."""
    voltage = event.voltage_v
    if voltage is None or voltage == 0 or VOLTAGE_NORMAL_MIN_V <= voltage <= VOLTAGE_NORMAL_MAX_V:
        return None
    if pool is None:
        return None

    band = "low" if voltage < VOLTAGE_NORMAL_MIN_V else "high"
    zone = str(zone or "GLOBAL")
    previous = await pool.fetchrow(
        """
        SELECT (event->>'voltage_v')::double precision AS voltage_v
        FROM security_events
        WHERE source_id = $1
          AND coalesce(event->>'zona', event->>'zone', 'GLOBAL') = $2
          AND jsonb_typeof(event->'voltage_v') = 'number'
        ORDER BY received_at DESC
        LIMIT 1
        """,
        event.source_id,
        zone,
    )
    if previous is not None:
        previous_voltage = float(previous["voltage_v"])
        previous_band = (
            "low" if 0 < previous_voltage < VOLTAGE_NORMAL_MIN_V
            else "high" if previous_voltage > VOLTAGE_NORMAL_MAX_V
            else None
        )
        # Emit once on entry to an abnormal band; subsequent out-of-range samples
        # continue to color the live camera amber without spamming notifications.
        if previous_band == band:
            return None
    return _alert(
        "warning",
        "VOLTAGE_FLUCTUATION",
        f"Fluctuación de voltaje: {voltage:.1f} V fuera del rango normal "
        f"{VOLTAGE_NORMAL_MIN_V}–{VOLTAGE_NORMAL_MAX_V} V en {zone}",
    )


def _alert(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}
