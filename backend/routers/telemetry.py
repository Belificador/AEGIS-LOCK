"""Authenticated telemetry ingestion, rules evaluation, persistence, and relay."""

import asyncio
import copy
import hmac
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.config import get_settings
from backend.core.log_safety import redact_sensitive_text
from backend.routers.ws_manager import authenticate_websocket, manager
from backend.services.postgres_client import postgres_service
from backend.services.rules_engine import evaluate_event
from backend.services.telemetry_ingest import parse_telemetry
from backend.services.camera_catalog import signed_camera_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
    settings = get_settings()
    rate_limiter = getattr(websocket.app.state, "websocket_rate_limiter", None)
    client_ip = websocket.client.host if websocket.client else "unknown"
    authorization = websocket.headers.get("authorization", "")
    claims: dict[str, Any] | None = None
    if authorization.startswith("Bearer "):
        if rate_limiter is not None:
            try:
                if not await rate_limiter.allow(f"ip:{client_ip}", "telemetry-auth", limit=20, window_seconds=60):
                    await websocket.close(code=4429, reason="Rate limit exceeded")
                    return
            except Exception:
                logger.exception("No se pudo consultar el rate limiter del emisor")
                await websocket.close(code=1013, reason="Rate limiter unavailable")
                return
        publisher = "gemelo-service"
        api_key = authorization.removeprefix("Bearer ")
        expected_key = settings.telemetry_api_key or ""
        if not expected_key or not hmac.compare_digest(api_key, expected_key):
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description="Invalid server-to-server telemetry credential",
            )
            await websocket.close(code=4401, reason="Invalid telemetry service credential")
            return
        origin = websocket.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description=f"Telemetry WebSocket origin rejected: {origin[:200]}",
            )
            await websocket.close(code=4403, reason="Origin not allowed")
            return
        await websocket.accept()
    else:
        claims = await authenticate_websocket(websocket, purpose="telemetry")
        if claims is None:
            return
        if claims.get("role") not in {"admin", "operator"}:
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description="Telemetry publisher role rejected",
            )
            await websocket.close(code=4403, reason="Telemetry publisher role required")
            return
        publisher = str(claims.get("sub", "operator"))

    started = time.monotonic()
    try:
        await websocket.send_json({"kind": "connection", "status": "authenticated"})
        while True:
            try:
                if claims and time.time() >= int(claims["exp"]):
                    await websocket.close(code=4401, reason="Access token expired")
                    return
                raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=5) if claims else await websocket.receive_text()
                if rate_limiter is not None:
                    allowed = await rate_limiter.allow(
                        f"ip:{client_ip}", "telemetry-frame-ip", limit=1200, window_seconds=60,
                    ) and await rate_limiter.allow(
                        f"publisher:{publisher}", "telemetry-frame-publisher", limit=600, window_seconds=60,
                    )
                    if not allowed:
                        await websocket.send_json({"kind": "error", "detail": "Rate limit exceeded"})
                        await websocket.close(code=4429, reason="Rate limit exceeded")
                        return
                if len(raw_text.encode("utf-8")) > settings.max_telemetry_event_bytes:
                    await websocket.send_json({"kind": "error", "detail": "Evento demasiado grande"})
                    continue
                raw_event = json.loads(raw_text)
                if not isinstance(raw_event, dict):
                    await websocket.send_json({"kind": "error", "detail": "El evento debe ser un objeto JSON"})
                    continue
                event, event_data = parse_telemetry(raw_event)
                persisted_event_data = copy.deepcopy(event_data)
            except asyncio.TimeoutError:
                continue
            except (ValueError, ValidationError) as exc:
                await websocket.send_json({"kind": "error", "detail": "Evento de telemetría inválido"})
                logger.warning("telemetry_validation_rejected publisher=%s reason=%s", publisher[:80], type(exc).__name__)
                continue

            if publisher != "gemelo-service" and event.event_type != "camera_selected":
                await websocket.send_json({"kind": "error", "detail": "Este token solo puede publicar selección de cámara"})
                logger.warning("telemetry_publish_denied publisher=%s type=%s", publisher[:80], event.event_type)
                continue

            if event.event_type == "camera_selected":
                raw_metadata = raw_event.get("metadata") if isinstance(raw_event.get("metadata"), dict) else {}
                camera_id = str(
                    raw_event.get("camera_id")
                    or raw_metadata.get("camera_id")
                    or raw_metadata.get("cameraId")
                    or raw_event.get("valor")
                    or ""
                )
                feed_url = signed_camera_url(
                    camera_id,
                    base_url=settings.gemelo_media_base_url,
                    secret=settings.telemetry_api_key or "",
                    expires_at=int(time.time()) + 3600,
                )
                if not feed_url:
                    await websocket.send_json({"kind": "error", "detail": "Cámara no reconocida o feed no configurado"})
                    logger.warning("camera_selection_denied publisher=%s", publisher[:80])
                    continue
                metadata = event_data.get("metadata") if isinstance(event_data.get("metadata"), dict) else {}
                event_data["metadata"] = {**metadata, "camera_id": camera_id, "feed_url": feed_url}
                await postgres_service.write_audit_log(
                    action="CAMERA_SELECTED",
                    performed_by=publisher,
                    details={"camera_id": camera_id, "zone": event_data.get("zona") or event_data.get("zone")},
                )

            alerts = evaluate_event(event)
            if event.event_type in {"acceso_pin", "access_pin"}:
                access_value = str(raw_event.get("valor") or "").strip().upper()
                if access_value in {"GRANTED", "DENIED", "LOCKOUT"}:
                    await postgres_service.write_audit_log(
                        action="PIN_ACCESS_GRANTED" if access_value == "GRANTED" else "PIN_ACCESS_DENIED",
                        performed_by=publisher,
                        details={
                            "door_name": raw_event.get("zona", raw_event.get("zone", "GLOBAL")),
                            "result": access_value,
                        },
                    )
            payload = {"kind": "telemetry", "event": event_data, "alerts": alerts}
            websocket.app.state.latest_event = payload
            persisted = False
            try:
                await asyncio.wait_for(postgres_service.persist_event(persisted_event_data, alerts), timeout=4)
                persisted = postgres_service.pool is not None
                if persisted_event_data.get("energy_kwh") is not None:
                    event_data["energy_kwh"] = persisted_event_data["energy_kwh"]
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
                event_data.get("zona", event_data.get("zone", "GLOBAL")),
                redact_sensitive_text(str(event_data.get("valor", event_data.get("temperature_c", ""))))[:120],
                persisted,
            )
    except WebSocketDisconnect as exc:
        if exc.code not in {1000, 1001}:
            try:
                await postgres_service.write_error_log(
                    error_type="WebSocket Disconnect",
                    description=f"/ws/telemetry emisor disconnected with code {exc.code}",
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
            except Exception:
                logger.exception("No se pudo guardar la desconexión del emisor")
        logger.info("Emisor de telemetría desconectado")
    except Exception:
        logger.exception("Conexión de telemetría finalizada por error")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
