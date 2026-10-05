"""Authenticated telemetry ingestion and rule evaluation."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.config import get_settings
from backend.models.schemas import TelemetryEvent
from backend.routers.ws_manager import authenticate_websocket, manager
from backend.services.rules_engine import evaluate_event
from backend.services.supabase_client import supabase_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
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
                if len(raw_text.encode("utf-8")) > get_settings().max_request_bytes:
                    await websocket.send_json({"kind": "error", "detail": "Evento demasiado grande"})
                    continue
                raw_event = json.loads(raw_text)
                event = TelemetryEvent.model_validate(raw_event)
            except ValidationError as exc:
                await websocket.send_json(
                    {"kind": "error", "detail": "Evento de telemetría inválido", "fields": len(exc.errors())}
                )
                continue
            except ValueError:
                await websocket.send_json({"kind": "error", "detail": "JSON inválido"})
                continue

            alerts = evaluate_event(event)
            event_data = event.model_dump(mode="json")
            websocket.app.state.latest_event = {"event": event_data, "alerts": alerts}
            payload = {"kind": "telemetry", "event": event_data, "alerts": alerts}
            await manager.broadcast(payload)
            try:
                await asyncio.wait_for(
                    supabase_service.persist_event(event_data, alerts), timeout=4
                )
            except Exception:
                logger.exception("No se pudo persistir evento de telemetría")
            await websocket.send_json({"kind": "ack", "event_id": str(event.event_id)})
    except WebSocketDisconnect:
        logger.info("Emisor de telemetría desconectado")
    except Exception:
        logger.exception("Conexión de telemetría finalizada por error")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
