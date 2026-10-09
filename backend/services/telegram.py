"""Server-side Telegram delivery for Argus and Hermes replies."""

import httpx

from backend.config import get_settings


async def send_telegram_message(text: str, *, chat_id: str | int | None = None) -> None:
    settings = get_settings()
    bot_token = (settings.telegram_bot_token or "").strip()
    recipient_value = settings.telegram_chat_id if chat_id is None else chat_id
    recipient = str(recipient_value or "").strip()
    if not bot_token or not recipient:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o el destino de Telegram")
    if not text or len(text) > 4000:
        raise ValueError("El mensaje de Argus debe contener entre 1 y 4000 caracteres")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=4)) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": recipient, "text": text},
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError:
        # The bot token is embedded in the Telegram URL; never log or rethrow it.
        raise RuntimeError("No se pudo conectar con Telegram para entregar el mensaje") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram rechazó el mensaje")
