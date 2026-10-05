"""Deterministic safety rules for incoming building telemetry."""

from typing import Any

from backend.models.schemas import TelemetryEvent


def evaluate_event(event: TelemetryEvent) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if event.temperature_c is not None and event.temperature_c > 38:
        alerts.append(_alert("critical", "HIGH_TEMPERATURE", f"Temperatura crítica: {event.temperature_c:.1f} °C"))
    if event.voltage_v == 0:
        alerts.append(_alert("critical", "POWER_LOSS", "Se detectó una lectura de 0 V"))
    if event.intrusion:
        alerts.append(_alert("critical", "INTRUSION", "Intrusión detectada"))
    if event.lockdown:
        alerts.append(_alert("lockdown", "LOCKDOWN", "El emisor reporta modo Lockdown activo"))
    return alerts


def _alert(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}
