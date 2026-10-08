"""Immediate rule-based Argus notifications; never delegate alarm decisions to the LLM."""

from datetime import datetime, timezone
import logging
from typing import Any

from backend.config import get_settings
from backend.services.postgres_client import postgres_service
from backend.services.telegram import send_telegram_message
from backend.services.argus_reporting import get_current_building_mode, get_current_occupancy

_logger = logging.getLogger(__name__)


async def notify_security_alert(event: dict[str, Any], alerts: list[dict[str, Any]], rate_limiter: Any) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    incidents = [
        alert for alert in alerts
        if alert.get("severity") in {"critical", "lockdown"}
        or alert.get("code") == "VOLTAGE_FLUCTUATION"
    ]
    if not incidents:
        return

    zone = str(event.get("zona") or event.get("zone") or "GLOBAL")[:120]
    source = str(event.get("source_id") or event.get("origen") or "aegis")[:80]
    timestamp = event.get("timestamp") or datetime.now().astimezone().isoformat()
    delivered = []
    for alert in incidents[:5]:
        code = str(alert.get("code") or "CRITICAL")[:60]
        if rate_limiter is not None and code != "VOLTAGE_FLUCTUATION":
            allowed = await rate_limiter.allow(
                f"{source}:{zone}:{code}", "telegram-critical-alert", limit=1, window_seconds=300,
            )
            if not allowed:
                continue
        message = str(alert.get("message") or "Incidente crítico detectado")[:240]
        delivered.append(f"• {message} · {zone}")

    if not delivered:
        return
    heading = "ALERTA CRÍTICA" if any(alert.get("severity") in {"critical", "lockdown"} for alert in incidents) else "AVISO DE VOLTAJE"
    text = f"AEGIS · HERMES · {heading}\nHora: {timestamp}\n" + "\n".join(delivered)
    await _send_to_recipients(text[:3900], action="critical_alert")


async def notify_mode_transition(
    action: str,
    *,
    actor: str,
    source: str,
    event_id: int | None,
    rate_limiter: Any = None,
) -> None:
    mode_details = {
        "LOCKDOWN_ACTIVATED": ("LOCKDOWN SIMULADO ACTIVADO", "LOCKDOWN"),
        "LOCKDOWN_RELEASED": ("LOCKDOWN SIMULADO LIBERADO", "NORMAL"),
        "EVACUATION_ACTIVATED": ("EVACUACIÓN SIMULADA ACTIVADA", "EVACUACIÓN"),
        "EVACUATION_RELEASED": ("EVACUACIÓN SIMULADA FINALIZADA", "NORMAL"),
    }
    details = mode_details.get(action)
    if details is None:
        return
    title, mode = details
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"AEGIS · HERMES · {title}",
        f"Actor AEGIS: {actor[:80]}",
        f"Origen: {source[:120]}",
        f"Hora UTC: {timestamp}",
    ]
    if mode == "EVACUACIÓN":
        try:
            occupancy = await get_current_occupancy()
            if event_id is not None and occupancy.get("total") is not None and rate_limiter is not None:
                if not await rate_limiter.allow(
                    f"{event_id}:{occupancy['total']}",
                    "telegram-evacuation-count",
                    limit=1,
                    window_seconds=86_400,
                ):
                    return
            lines.append(_occupancy_line(occupancy))
        except Exception as exc:
            _logger.warning("argus_evacuation_snapshot_failed error=%s", type(exc).__name__)
            lines.append("Personas en el edificio: aforo no disponible.")
    await _send_to_recipients("\n".join(lines), action="mode_transition")


async def notify_access_entry(event: dict[str, Any]) -> None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    direction = str(metadata.get("access_direction") or "").strip().lower()
    result = str(event.get("valor") or "").strip().upper()
    if result != "GRANTED" or direction != "entry":
        return
    door = str(event.get("zona") or event.get("zone") or metadata.get("door_name") or "puerta desconocida")[:120]
    timestamp = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat())[:50]
    # Do not include visitor names, PINs, or PIN identifiers in Telegram.
    await _send_to_recipients(
        f"AEGIS · HERMES · ENTRADA AUTORIZADA\nAcceso: {door}\nHora: {timestamp}",
        action="authorized_entry",
    )


async def notify_evacuation_occupancy(rate_limiter: Any) -> None:
    """Send changed, fresh occupancy totals while an evacuation is active."""
    try:
        mode = await get_current_building_mode()
        if mode["mode"] != "EVACUACIÓN" or mode["event_id"] is None:
            return
        occupancy = await get_current_occupancy()
        if occupancy.get("total") is None:
            return
        await _notify_evacuation_count(int(mode["event_id"]), occupancy, rate_limiter=rate_limiter)
    except Exception as exc:
        _logger.warning("argus_evacuation_count_failed error=%s", type(exc).__name__)


async def _notify_evacuation_count(event_id: int, occupancy: dict[str, Any], *, rate_limiter: Any) -> None:
    total = occupancy.get("total")
    if total is None:
        return
    if rate_limiter is not None:
        allowed = await rate_limiter.allow(
            f"{event_id}:{total}", "telegram-evacuation-count", limit=1, window_seconds=86_400,
        )
        if not allowed:
            return
    timestamp = occupancy.get("updated_at") or "hora no disponible"
    text = (
        "AEGIS · HERMES · ACTUALIZACIÓN DE EVACUACIÓN\n"
        f"Personas que permanecen en el edificio: {total}\n"
        f"Última lectura: {timestamp}"
    )
    await _send_to_recipients(text, action="evacuation_count")


def _occupancy_line(occupancy: dict[str, Any]) -> str:
    total = occupancy.get("total")
    if total is None:
        return "Personas en el edificio: aforo desactualizado o no disponible."
    return f"Personas que permanecen en el edificio: {total}. Última lectura: {occupancy.get('updated_at') or 'no disponible'}"


async def _telegram_recipients(settings: Any) -> list[str]:
    mapped_users = settings.authorized_telegram_users
    if mapped_users:
        if postgres_service.pool is None:
            return []
        active_ids = []
        for user_id, username in mapped_users.items():
            if username is None or await postgres_service.get_user(username) is not None:
                active_ids.append(str(user_id))
        return sorted(active_ids)
    fallback = str(settings.telegram_chat_id or "").strip()
    return [fallback] if fallback else []


async def _send_to_recipients(text: str, *, action: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    try:
        recipients = await _telegram_recipients(settings)
    except Exception as exc:
        _logger.warning("argus_telegram_recipient_lookup_failed action=%s error=%s", action, type(exc).__name__)
        return
    for chat_id in recipients:
        try:
            await send_telegram_message(text[:3900], chat_id=chat_id)
        except Exception as exc:
            _logger.warning("argus_telegram_delivery_failed action=%s error=%s", action, type(exc).__name__)
