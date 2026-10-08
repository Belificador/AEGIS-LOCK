"""Server-side Telegram notifier for Argus."""

import httpx

from backend.config import get_settings


async def send_telegram_message(text: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
    if not text or len(text) > 4000:
        raise ValueError("El mensaje de Argus debe contener entre 1 y 4000 caracteres")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=4)) as client:
            response = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError:
        # The bot token is embedded in the Telegram URL; never log or rethrow it.
        raise RuntimeError("No se pudo enviar el reporte de Argus a Telegram") from None
    if result.get("ok") is not True:
        raise RuntimeError("Telegram rechazó el reporte de Argus")
