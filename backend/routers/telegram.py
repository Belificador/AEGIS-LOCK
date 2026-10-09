"""Private, allow-listed Telegram webhook for read-only Hermes queries."""

from collections import deque
import hmac
import logging
from time import monotonic
import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError

from backend.agents.argus.agent import ask_argus
from backend.agents.argus.client import OpenRouterError
from backend.config import get_settings
from backend.core.rate_limit import limiter
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
_sender_requests: dict[int, deque[float]] = {}


@router.post("/webhook")
@limiter.limit("120/minute")
async def receive_telegram_update(
    request: Request,
    secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
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
        isinstance(sender_id, bool) or not isinstance(sender_id, int)
        or isinstance(chat_id, bool) or not isinstance(chat_id, int)
        or chat.get("type") != "private" or chat_id != sender_id or sender.get("is_bot") is True
    ):
        return {"ok": True}
    if not _sender_is_allowed_rate(sender_id):
        await _reply(chat_id, "Límite de consultas alcanzado. Espera un minuto e inténtalo de nuevo.")
        return {"ok": True}

    aegis_username = settings.authorized_telegram_users.get(sender_id)
    if aegis_username is None:
        await _reply(chat_id, "Cuenta de Telegram no autorizada para consultar AEGIS.")
        return {"ok": True}
    try:
        user = await postgres_service.get_user(aegis_username)
    except Exception as exc:
        logger.warning("hermes_account_lookup_failed error=%s", type(exc).__name__)
        await _reply(chat_id, "No pude validar tu cuenta AEGIS en este momento.")
        return {"ok": True}
    if user is None:
        await _reply(chat_id, "La cuenta AEGIS vinculada no está activa. Contacta a un administrador.")
        return {"ok": True}

    update_id = update.get("update_id")
    if isinstance(update_id, int) and not isinstance(update_id, bool):
        try:
            if postgres_service.pool is None:
                raise RuntimeError("PostgreSQL no está configurado")
            claimed = await postgres_service.pool.fetchval(
                """
                INSERT INTO telegram_webhook_updates (update_id) VALUES ($1)
                ON CONFLICT (update_id) DO NOTHING RETURNING update_id
                """,
                update_id,
            )
            if claimed is None:
                return {"ok": True}
        except Exception as exc:
            logger.warning("hermes_update_dedup_failed error=%s", type(exc).__name__)
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

    claims: dict[str, Any] = {
        "sub": user["username"],
        "username": user["username"],
        "role": user["role"],
        "channel": "telegram",
    }
    try:
        answer = await ask_argus(prompt, claims)
    except OpenRouterError as exc:
        logger.warning("hermes_argus_unavailable error=%s", type(exc).__name__)
        answer = "Argus no está disponible ahora. Inténtalo de nuevo en un momento."
    except Exception as exc:
        logger.exception("hermes_argus_request_failed error=%s", type(exc).__name__)
        answer = "No pude completar la consulta de AEGIS. Inténtalo de nuevo."
    await _reply(chat_id, answer)
    return {"ok": True}


def _sender_is_allowed_rate(sender_id: int, *, now: float | None = None) -> bool:
    current = monotonic() if now is None else now
    requests = _sender_requests.setdefault(sender_id, deque())
    while requests and current - requests[0] >= 60:
        requests.popleft()
    if len(requests) >= 12:
        return False
    requests.append(current)
    if len(_sender_requests) > 2048:
        oldest_key = next((key for key in _sender_requests if key != sender_id), None)
        if oldest_key is not None:
            _sender_requests.pop(oldest_key, None)
    return True


def _resolve_telegram_command(text: str) -> tuple[str, str | None]:
    trimmed = text.strip()
    if not trimmed:
        return "", _HELP
    first, _, remainder = trimmed.partition(" ")
    command = _normalize(first.split("@", 1)[0].lstrip("/"))
    normalized_text = _normalize(trimmed.lstrip("/"))
    if command in {"start", "help", "ayuda"}:
        return "", _HELP
    if command in {"lockdown", "evacuacion", "pin"}:
        return "", "Hermes permite consultas, pero no activa modos ni genera PINes desde Telegram."
    prompt = _COMMAND_PROMPTS.get(command)
    if prompt is not None:
        if command == "camara" and remainder.strip():
            return f"Comprueba la cámara {remainder.strip()} del catálogo AEGIS.", None
        return prompt, None
    alias = normalized_text.split(maxsplit=1)[0] if normalized_text else ""
    if alias in _COMMAND_PROMPTS:
        return _COMMAND_PROMPTS[alias], None
    if trimmed.startswith("/"):
        return "", _HELP
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
            logger.warning("hermes_reply_failed error=%s", type(exc).__name__)
            return
