"""Private, allowlisted Telegram entry point for one-shot Argus requests."""

import hmac
import logging
import unicodedata
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError

from backend.agents.argus.agent import ask_argus
from backend.agents.argus.client import OpenRouterError
from backend.config import get_settings
from backend.models.schemas import ChatRequest
from backend.services.postgres_client import postgres_service
from backend.services.telegram import send_telegram_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])

_HELP = """Hermes · Argus AEGIS
Consultas disponibles:
/temperatura · /bitacora · /aforo · /estado · /accesos · /ayuda
También puedes preguntar por una cámara del catálogo.
Hermes responde consultas; no activa modos ni genera PINes desde Telegram."""

_COMMAND_PROMPTS = {
    "temperatura": "Consulta la temperatura más reciente del edificio. Indica si no hay lectura disponible.",
    "temp": "Consulta la temperatura más reciente del edificio. Indica si no hay lectura disponible.",
    "bitacora": "Consulta y resume la bitácora reciente de AEGIS.",
    "actividad": "Consulta y resume la bitácora reciente de AEGIS.",
    "aforo": "Consulta cuántas personas hay actualmente en el edificio por zona. No inventes conteos.",
    "ocupacion": "Consulta cuántas personas hay actualmente en el edificio por zona. No inventes conteos.",
    "estado": "Consulta el estado actual del edificio y señala qué lecturas no están disponibles.",
    "accesos": "Resume los accesos recientes autorizados o denegados; no incluyas nombres ni PINes.",
    "camara": "Comprueba la cámara indicada del catálogo AEGIS.",
    "camaras": "Indica las cámaras disponibles en el catálogo AEGIS y no inventes cámaras.",
}


@router.post("/webhook")
async def receive_telegram_update(
    request: Request,
    secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, bool]:
    settings = get_settings()
    expected_secret = settings.telegram_webhook_secret or ""
    if not expected_secret or not secret_token or not hmac.compare_digest(secret_token, expected_secret):
        raise HTTPException(status_code=403, detail="Webhook de Telegram no autorizado")

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    if not isinstance(update, dict):
        return {"ok": True}

    message = update.get("message")
    if not isinstance(message, dict):
        return {"ok": True}
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return {"ok": True}
    sender_id = sender.get("id")
    chat_id = chat.get("id")
    if (
        isinstance(sender_id, bool)
        or not isinstance(sender_id, int)
        or isinstance(chat_id, bool)
        or not isinstance(chat_id, int)
        or chat.get("type") != "private"
        or sender.get("is_bot") is True
    ):
        return {"ok": True}

    limiter = getattr(request.app.state, "websocket_rate_limiter", None)
    if limiter is not None:
        try:
            if not await limiter.allow(f"telegram:{sender_id}", "telegram-requests", limit=12, window_seconds=60):
                await _reply(chat_id, "Límite de consultas alcanzado. Espera un minuto e inténtalo de nuevo.")
                return {"ok": True}
        except Exception as exc:
            logger.warning("telegram_rate_limit_unavailable error=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Control de solicitudes no disponible") from exc

    aegis_username = settings.authorized_telegram_users.get(sender_id)
    if aegis_username is None:
        await _reply(chat_id, "Cuenta de Telegram no autorizada para consultar AEGIS.")
        return {"ok": True}
    try:
        user = await postgres_service.get_user(aegis_username)
    except Exception as exc:
        logger.warning("telegram_account_lookup_failed error=%s", type(exc).__name__)
        await _reply(chat_id, "No pude validar tu cuenta AEGIS en este momento.")
        return {"ok": True}
    if user is None:
        await _reply(chat_id, "La cuenta AEGIS vinculada no está activa. Contacta a un administrador.")
        return {"ok": True}

    update_id = update.get("update_id")
    if isinstance(update_id, int) and not isinstance(update_id, bool):
        try:
            if postgres_service.pool is None:
                raise RuntimeError("PostgreSQL is not configured")
            claimed = await postgres_service.pool.fetchval(
                """
                INSERT INTO telegram_webhook_updates (update_id)
                VALUES ($1)
                ON CONFLICT (update_id) DO NOTHING
                RETURNING update_id
                """,
                update_id,
            )
            if claimed is None:
                return {"ok": True}
        except Exception as exc:
            logger.warning("telegram_update_dedup_failed error=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="No se pudo registrar la actualización") from exc

    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        await _reply(chat_id, "Por ahora Hermes recibe consultas de texto. Envía /ayuda para ver comandos.")
        return {"ok": True}

    try:
        payload = ChatRequest(message=text.strip())
    except ValidationError:
        await _reply(chat_id, "La consulta debe tener entre 1 y 1200 caracteres.")
        return {"ok": True}

    prompt, direct_reply = _resolve_telegram_command(payload.message)
    if direct_reply is not None:
        await _reply(chat_id, direct_reply)
        return {"ok": True}

    # The actual AEGIS role is loaded from PostgreSQL. The Telegram channel
    # independently suppresses write-capable tools in v1.
    claims: dict[str, Any] = {
        "sub": user["username"],
        "username": user["username"],
        "role": user["role"],
        "channel": "telegram",
    }
    try:
        answer = await ask_argus(prompt, claims)
    except OpenRouterError as exc:
        logger.warning("telegram_argus_unavailable error=%s", type(exc).__name__)
        answer = "Argus no está disponible ahora. Inténtalo de nuevo en un momento."
    except Exception as exc:
        logger.exception("telegram_argus_request_failed error=%s", type(exc).__name__)
        answer = "No pude completar la consulta de AEGIS. Inténtalo de nuevo."
    await _reply(chat_id, answer)
    return {"ok": True}


def _resolve_telegram_command(text: str) -> tuple[str, str | None]:
    trimmed = text.strip()
    if not trimmed:
        return "", _HELP
    first, _, remainder = trimmed.partition(" ")
    command = first.split("@", 1)[0].lstrip("/")
    normalized = _normalize(command)
    normalized_text = _normalize(trimmed.lstrip("/"))

    if normalized in {"start", "help", "ayuda"}:
        return "", _HELP
    if normalized in {"lockdown", "evacuacion", "pin"}:
        return "", "Hermes permite consultas, pero no activa modos ni genera PINes desde Telegram."

    prompt = _COMMAND_PROMPTS.get(normalized)
    if prompt is not None:
        if normalized == "camara" and remainder.strip():
            return f"Comprueba la cámara {remainder.strip()} del catálogo AEGIS.", None
        return prompt, None

    # Accept the advertised words without requiring slash-prefixed commands.
    alias = normalized_text.split(maxsplit=1)[0] if normalized_text else ""
    prompt = _COMMAND_PROMPTS.get(alias)
    if prompt is not None:
        return prompt, None
    if trimmed.startswith("/"):
        return "", _HELP
    # Each message is an independent Argus request; no Telegram conversation history is stored.
    return text, None


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


async def _reply(chat_id: int, text: str) -> None:
    remaining = text.strip() or "Argus no devolvió texto."
    while remaining:
        if len(remaining) <= 3900:
            part, remaining = remaining, ""
        else:
            split_at = remaining.rfind("\n", 0, 3900)
            if split_at < 1000:
                split_at = 3900
            part, remaining = remaining[:split_at], remaining[split_at:].lstrip()
        try:
            await send_telegram_message(part, chat_id=chat_id)
        except Exception as exc:
            logger.warning("telegram_reply_failed error=%s", type(exc).__name__)
            return
