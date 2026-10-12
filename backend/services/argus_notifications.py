"""Power-loss notices delivered to authorized AEGIS administrators over Hermes."""

import logging
import re
from typing import Any, Literal

from backend.config import get_settings
from backend.services.postgres_client import postgres_service
from backend.services.telegram import send_telegram_message

logger = logging.getLogger(__name__)
PowerLossTransition = Literal["loss", "restored"]


def classify_power_loss_transition(previous_voltage: Any, current_voltage: Any) -> PowerLossTransition | None:
    previous = _finite_voltage(previous_voltage)
    current = _finite_voltage(current_voltage)
    if current == 0 and previous != 0:
        return "loss"
    if previous == 0 and current is not None and current > 0:
        return "restored"
    return None


async def notify_power_loss_transition(
    *,
    transition: PowerLossTransition,
    source_id: str,
    zone: str,
    voltage: float,
    timestamp: str,
) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.authorized_telegram_users:
        return

    title, reading = (
        ("PÉRDIDA DE ALIMENTACIÓN", "0 V")
        if transition == "loss"
        else ("ALIMENTACIÓN RESTABLECIDA", f"{voltage:g} V")
    )
    message = (
        f"AEGIS · HERMES · {title}\n"
        f"Zona: {_single_line(zone, 100)}\n"
        f"Lectura: {reading}\n"
        f"Fuente: {_single_line(source_id, 80)}\n"
        f"Hora: {_single_line(timestamp, 50)}"
    )
    for telegram_id, username in settings.authorized_telegram_users.items():
        try:
            user = await postgres_service.get_user(username)
            if user is None or user.get("role") != "admin":
                continue
            await send_telegram_message(message, chat_id=telegram_id)
        except Exception as exc:
            logger.warning("hermes_power_loss_delivery_failed error=%s", type(exc).__name__)


def _finite_voltage(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _single_line(value: str, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value)).strip()[:limit] or "GLOBAL"
