"""Authenticated telemetry ingestion, rules evaluation, persistence, and relay."""

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.config import get_settings
from backend.routers.ws_manager import authenticate_websocket, manager
from backend.services.postgres_client import postgres_service
from backend.services.rules_engine import evaluate_event
from backend.services.telemetry_ingest import parse_telemetry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
    settings = get_settings()
    authorization = websocket.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        api_key = authorization.removeprefix("Bearer ")
        expected_key = settings.telemetry_api_key or ""
        if not expected_key or not hmac.compare_digest(api_key, expected_key):
            await websocket.close(code=4401, reason="Invalid telemetry service credential")
            return
        origin = websocket.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            await websocket.close(code=4403, reason="Origin not allowed")
            return
        await websocket.accept()
    else:
        claims = await authenticate_websocket(websocket)
        if claims is None:
            return
        if claims.get("role") not in {"admin", "operator"}:
            await websocket.close(code=4403, reason="Telemetry publisher role required")
            return

    try:
        await websocket.send_json({"kind": "connection", "status": "authenticated"})
        while True:
            try:
                raw_text = await websocket.receive_text()
                if len(raw_text.encode("utf-8")) > settings.max_request_bytes:
                    await websocket.send_json({"kind": "error", "detail": "Evento demasiado grande"})
                    continue
                raw_event = json.loads(raw_text)
                if not isinstance(raw_event, dict):
                    await websocket.send_json({"kind": "error", "detail": "El evento debe ser un objeto JSON"})
                    continue
                event, event_data = parse_telemetry(raw_event)
            except (ValueError, ValidationError) as exc:
                await websocket.send_json({"kind": "error", "detail": "Evento de telemetría inválido"})
                logger.info("Evento de telemetría rechazado: %s", str(exc)[:300])
                continue

            alerts = evaluate_event(event)
            payload = {"kind": "telemetry", "event": event_data, "alerts": alerts}
            websocket.app.state.latest_event = payload
            persisted = False
            try:
                await asyncio.wait_for(postgres_service.persist_event(event_data, alerts), timeout=4)
                persisted = postgres_service.pool is not None
            except Exception:
                logger.exception("No se pudo persistir evento de telemetría")

            await manager.broadcast(payload)
            await websocket.send_json({
                "kind": "ack",
                "event_id": event_data["event_id"],
                "persisted": persisted,
                "alerts": alerts,
            })
            logger.info(
                "[TELEMETRÍA RECIBIDA] Tipo: %s | Zona: %s | Valor: %s | persisted=%s",
                event.event_type,
                raw_event.get("zona", raw_event.get("zone")),
                raw_event.get("valor", raw_event.get("temperature_c")),
                persisted,
            )
    except WebSocketDisconnect:
        logger.info("Emisor de telemetría desconectado")
    except Exception:
        logger.exception("Conexión de telemetría finalizada por error")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
