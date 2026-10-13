"""Fire-and-forget critical notices to allow-listed AEGIS administrators.

Notification work is never awaited by the telemetry WebSocket handler and is
not placed in a queue. The voltage baseline is seeded once at API startup and
then updated in memory only after telemetry persistence succeeds.
"""

import asyncio
import logging
from time import monotonic
from typing import Any, Literal

from backend.config import get_settings
from backend.services.postgres_client import postgres_service
from backend.services.telegram import send_telegram_message

logger = logging.getLogger(__name__)
PowerLossTransition = Literal["loss", "restored"]

_last_voltage: dict[tuple[str, str], float] = {}
_last_notice_at: dict[str, float] = {}
_in_flight: set[asyncio.Task[None]] = set()
_NOTICE_COOLDOWN_SECONDS = 300


def seed_power_voltage_state(events: list[dict[str, Any]]) -> None:
    """Warm the in-memory transition baseline once from persisted snapshots."""
    for item in events:
        event = item.get("event") if isinstance(item, dict) else None
        if not isinstance(event, dict):
            continue
        voltage = _finite_voltage(event.get("voltage_v"))
        if voltage is None:
            continue
        source = str(event.get("source_id") or event.get("origen") or "aegis")
        zone = str(event.get("zone") or event.get("zona") or "GLOBAL")
        _last_voltage[(source, zone)] = voltage


def schedule_telemetry_notices(event: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
    """Schedule Telegram I/O after persistence without delaying telemetry ACKs."""
    source = str(event.get("source_id") or event.get("origen") or "aegis")
    zone = str(event.get("zone") or event.get("zona") or "GLOBAL")
    voltage = _finite_voltage(event.get("voltage_v"))

    if voltage is not None:
        transition = _record_power_transition(source, zone, voltage)
        if transition and _reserve_notice(f"power:{source}:{zone}:{transition}"):
            _schedule(_send_power_transition(source, zone, voltage, transition, event.get("timestamp")))

    selected = []
    for alert in alerts:
        if not isinstance(alert, dict) or alert.get("severity") not in {"critical", "lockdown"}:
            continue
        code = str(alert.get("code") or "CRITICAL")
        if code == "POWER_LOSS":
            continue
        if code in {"ENTRY_DURING_LOCKDOWN", "ACCESS_GRANTED_DURING_LOCKDOWN", "ACCESS_ATTEMPT_DURING_LOCKDOWN"}:
            event_id = str(event.get("event_id") or event.get("eventId") or "unknown")
            notice_key = f"access:{code}:{event_id}"
        else:
            notice_key = f"alert:{code}:{source}:{zone}"
        if _reserve_notice(notice_key):
            selected.append({"code": code, "message": str(alert.get("message") or "Alerta crítica")[:240]})
    if selected:
        _schedule(_send_critical_alerts(source, zone, str(event.get("timestamp") or "hora no disponible"), selected))


def schedule_mode_transition(action: str, actor: str, details: dict[str, Any], audit_id: int | None) -> None:
    titles = {
        "LOCKDOWN_ACTIVATED": "LOCKDOWN SIMULADO ACTIVADO",
        "LOCKDOWN_RELEASED": "LOCKDOWN SIMULADO LIBERADO",
        "EVACUATION_ACTIVATED": "EVACUACIÓN SIMULADA ACTIVADA",
        "EVACUATION_RELEASED": "EVACUACIÓN SIMULADA FINALIZADA",
    }
    title = titles.get(action)
    if title is None or not _reserve_notice(f"mode:{action}:{audit_id if audit_id is not None else actor}"):
        return
    source = str(details.get("source") or "Dashboard")[:100]
    text = f"AEGIS · HERMES · {title}\nActor: {actor[:80]}\nOrigen: {source}"
    _schedule(_send_to_admins(text))


def _record_power_transition(source: str, zone: str, voltage: float) -> PowerLossTransition | None:
    key = (source, zone)
    previous = _last_voltage.get(key)
    _last_voltage[key] = voltage
    if voltage == 0 and previous != 0:
        return "loss"
    if previous == 0 and voltage > 0:
        return "restored"
    return None


def _reserve_notice(key: str) -> bool:
    now = monotonic()
    previous = _last_notice_at.get(key)
    if previous is not None and now - previous < _NOTICE_COOLDOWN_SECONDS:
        return False
    _last_notice_at[key] = now
    if len(_last_notice_at) > 4096:
        cutoff = now - _NOTICE_COOLDOWN_SECONDS
        for old_key, sent_at in tuple(_last_notice_at.items()):
            if sent_at < cutoff:
                _last_notice_at.pop(old_key, None)
    return True


def _schedule(coroutine: Any) -> None:
    task = asyncio.create_task(coroutine)
    _in_flight.add(task)
    task.add_done_callback(_finish_task)


def _finish_task(task: asyncio.Task[None]) -> None:
    _in_flight.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("hermes_notification_failed error=%s", type(error).__name__)


async def _send_power_transition(
    source: str,
    zone: str,
    voltage: float,
    transition: PowerLossTransition,
    timestamp: Any,
) -> None:
    title, reading = (
        ("PÉRDIDA DE ALIMENTACIÓN", "0 V")
        if transition == "loss"
        else ("ALIMENTACIÓN RESTABLECIDA", f"{voltage:g} V")
    )
    text = (
        f"AEGIS · HERMES · {title}\n"
        f"Zona: {_single_line(zone, 100)}\nLectura: {reading}\n"
        f"Fuente: {_single_line(source, 80)}\nHora: {_single_line(str(timestamp or 'no disponible'), 50)}"
    )
    await _send_to_admins(text)


async def _send_critical_alerts(source: str, zone: str, timestamp: str, alerts: list[dict[str, str]]) -> None:
    details = "\n".join(f"• {alert['message']}" for alert in alerts[:5])
    text = (
        "AEGIS · HERMES · ALERTA CRÍTICA\n"
        f"Zona: {_single_line(zone, 100)}\nFuente: {_single_line(source, 80)}\n"
        f"Hora: {_single_line(timestamp, 50)}\n{details}"
    )
    await _send_to_admins(text)


async def _send_to_admins(text: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.authorized_telegram_users:
        return
    for chat_id, username in settings.authorized_telegram_users.items():
        try:
            user = await postgres_service.get_user(username)
            if user is None or user.get("role") != "admin":
                continue
            await send_telegram_message(text[:3900], chat_id=chat_id)
        except Exception as exc:
            logger.warning("hermes_admin_notification_failed error=%s", type(exc).__name__)


def _finite_voltage(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric and abs(numeric) != float("inf") else None


def _single_line(value: str, limit: int) -> str:
    return " ".join(str(value).split())[:limit] or "GLOBAL"
