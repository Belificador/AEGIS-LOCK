"""Server-side Telegram notifier for Argus."""

import httpx

from backend.config import get_settings


async def send_telegram_message(text: str) -> None:
    settings = get_settings()
    bot_token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not bot_token or not chat_id:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
    if not text or len(text) > 4000:
        raise ValueError("El mensaje de Argus debe contener entre 1 y 4000 caracteres")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=4)) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except httpx.HTTPError:
        # The bot token is embedded in the Telegram URL; never log or rethrow it.
        raise RuntimeError("No se pudo conectar con Telegram para enviar el reporte de Argus") from None

    try:
        result = response.json()
    except ValueError:
        result = None
    if not response.is_success or not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(_telegram_rejection_reason(response, result, bot_token, chat_id)) from None


def _telegram_rejection_reason(
    response: httpx.Response,
    result: object,
    bot_token: str,
    chat_id: str,
) -> str:
    error_code = response.status_code
    description = "Telegram devolvió una respuesta inválida"
    if isinstance(result, dict):
        candidate_code = result.get("error_code")
        if isinstance(candidate_code, int):
            error_code = candidate_code
        candidate_description = result.get("description")
        if isinstance(candidate_description, str) and candidate_description.strip():
            description = candidate_description

    # Telegram's descriptions are normally generic; redact credentials and the
    # destination anyway before the reason reaches public GitHub Actions logs.
    for secret in (bot_token, chat_id):
        if secret:
            description = description.replace(secret, "[redacted]")
    description = " ".join(description.split())[:240]
    return f"Telegram rechazó el reporte (HTTP {error_code}): {description}"
