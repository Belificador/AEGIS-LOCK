"""Immediate rule-based Argus notifications; never delegate alarm decisions to the LLM."""

from datetime import datetime
import logging
from typing import Any

from backend.config import get_settings
from backend.services.telegram import send_telegram_message

_logger = logging.getLogger(__name__)


async def notify_security_alert(event: dict[str, Any], alerts: list[dict[str, Any]], rate_limiter: Any) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    critical = [alert for alert in alerts if alert.get("severity") in {"critical", "lockdown"}]
    if not critical:
        return

    zone = str(event.get("zona") or event.get("zone") or "GLOBAL")[:120]
    source = str(event.get("source_id") or event.get("origen") or "aegis")[:80]
    timestamp = event.get("timestamp") or datetime.now().astimezone().isoformat()
    delivered = []
    for alert in critical[:5]:
        code = str(alert.get("code") or "CRITICAL")[:60]
        if rate_limiter is not None:
            allowed = await rate_limiter.allow(
                f"{source}:{zone}:{code}", "telegram-critical-alert", limit=1, window_seconds=300,
            )
            if not allowed:
                continue
        message = str(alert.get("message") or "Incidente crítico detectado")[:240]
        delivered.append(f"• {message} · {zone}")

    if not delivered:
        return
    text = f"AEGIS · ARGUS · ALERTA CRÍTICA\nHora: {timestamp}\n" + "\n".join(delivered)
    try:
        await send_telegram_message(text[:3900])
    except Exception as exc:
        _logger.warning("argus_telegram_alert_failed error=%s", type(exc).__name__)
