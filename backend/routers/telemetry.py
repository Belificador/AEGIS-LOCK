"""Authenticated telemetry ingestion, rules evaluation, persistence, and relay."""

import asyncio
import copy
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.config import get_settings
from backend.routers.ws_manager import authenticate_websocket, manager
from backend.services.argus_notifications import (
    notify_access_entry,
    notify_evacuation_occupancy,
    notify_security_alert,
)
from backend.services.postgres_client import postgres_service
from backend.services.rules_engine import evaluate_event, evaluate_voltage_fluctuation
from backend.services.telemetry_ingest import parse_telemetry
from backend.services.camera_catalog import signed_camera_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telemetry"])
_PERSISTENCE_TASK_LIMIT = 256
_persistence_tasks: set[asyncio.Task[None]] = set()


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
            raw_event: dict[str, Any] | None = None
            try:
                if claims and time.time() >= int(claims["exp"]):
                    await websocket.close(code=4401, reason="Access token expired")
                    return
                raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=5) if claims else await websocket.receive_text()
                if rate_limiter is not None:
                    # A global Gemelo slider fans one change out to six zones and
                    # voltage plus illumination; allow that burst without dropping
                    # a valid state snapshot, while retaining a bounded per-minute cap.
                    allowed = await rate_limiter.allow(
                        f"ip:{client_ip}", "telemetry-frame-ip", limit=3600, window_seconds=60,
                    ) and await rate_limiter.allow(
                        f"publisher:{publisher}", "telemetry-frame-publisher", limit=3600, window_seconds=60,
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
                received_monotonic = time.monotonic()
                metadata = event_data.get("metadata") if isinstance(event_data.get("metadata"), dict) else {}
                access_target_user = metadata.pop("target_user", None)
                event_data["metadata"] = metadata
                persisted_event_data = _persisted_event_data(event, event_data)
            except asyncio.TimeoutError:
                continue
            except (ValueError, ValidationError) as exc:
                rejected_event_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
                error_payload = {"kind": "error", "detail": "Evento de telemetría inválido"}
                if isinstance(rejected_event_id, str) and len(rejected_event_id) <= 80:
                    error_payload["event_id"] = rejected_event_id
                await websocket.send_json(error_payload)
                logger.warning(
                    "telemetry_validation_rejected publisher=%s event_id=%s reason=%s",
                    publisher[:80],
                    str(rejected_event_id or "")[:80],
                    type(exc).__name__,
                )
                continue

            if publisher != "gemelo-service" and event.event_type != "camera_selected":
                await websocket.send_json({
                    "kind": "error",
                    "detail": "Este token solo puede publicar selección de cámara",
                    "event_id": event_data["event_id"],
                })
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
            if event.voltage_v is not None and event.voltage_v != 0:
                try:
                    fluctuation = await evaluate_voltage_fluctuation(
                        event,
                        pool=postgres_service.pool,
                        zone=str(event_data.get("zona") or event_data.get("zone") or "GLOBAL"),
                    )
                    if fluctuation:
                        alerts.append(fluctuation)
                except Exception as exc:
                    logger.warning("voltage_quality_check_failed error=%s", type(exc).__name__)
            if alerts:
                notification = asyncio.create_task(
                    notify_security_alert(event_data, alerts, rate_limiter),
                    name="argus-telegram-alert",
                )
                notification.add_done_callback(_log_notification_failure)
            if event.event_type in {"acceso_pin", "access_pin"}:
                access_value = str(raw_event.get("valor") or "").strip().upper()
                if access_value in {"GRANTED", "DENIED", "LOCKOUT"}:
                    await postgres_service.write_audit_log(
                        action="PIN_ACCESS_GRANTED" if access_value == "GRANTED" else "PIN_ACCESS_DENIED",
                        performed_by=publisher,
                        details={
                            "door_name": raw_event.get("zona", raw_event.get("zone", "GLOBAL")),
                            "result": access_value,
                            "pin_id": event_data.get("metadata", {}).get("pin_id"),
                            "target_user": access_target_user,
                            "access_direction": event_data.get("metadata", {}).get("access_direction"),
                        },
                    )
                    if access_value == "GRANTED" and event_data.get("metadata", {}).get("access_direction") == "entry":
                        notification = asyncio.create_task(
                            notify_access_entry(event_data),
                            name="argus-telegram-authorized-entry",
                        )
                        notification.add_done_callback(_log_notification_failure)
            payload = {"kind": "telemetry", "event": event_data, "alerts": alerts}
            websocket.app.state.latest_event = payload
            persisted = False
            await manager.broadcast(payload)
            broadcast_ms = round((time.monotonic() - received_monotonic) * 1000)
            persistence_queued = False
            if postgres_service.pool is not None:
                persistence_queued = await manager.enqueue_persistence(persisted_event_data, alerts)
                if not persistence_queued and len(_persistence_tasks) < _PERSISTENCE_TASK_LIMIT:
                    task = asyncio.create_task(
                        _persist_event_background(
                            copy.deepcopy(persisted_event_data),
                            copy.deepcopy(alerts),
                            websocket.app,
                            rate_limiter,
                            event.occupancy is not None,
                        ),
                        name=f"telemetry-persist-{event.event_id}",
                    )
                    _persistence_tasks.add(task)
                    task.add_done_callback(_persistence_tasks.discard)
                    persistence_queued = True
                elif not persistence_queued:
                    try:
                        await asyncio.wait_for(postgres_service.persist_event(persisted_event_data, alerts), timeout=4)
                        persisted = True
                        if event.occupancy is not None:
                            notification = asyncio.create_task(
                                notify_evacuation_occupancy(rate_limiter),
                                name="argus-telegram-evacuation-count",
                            )
                            notification.add_done_callback(_log_notification_failure)
                    except Exception:
                        logger.exception("No se pudo persistir evento de telemetría; cola de persistencia llena")
            await websocket.send_json({
                "kind": "ack",
                "event_id": event_data["event_id"],
                "persisted": persisted,
                "queued_for_persistence": persistence_queued,
                "alerts": alerts,
            })
            logger.info(
                "telemetry_broadcast_dispatched event_id=%s type=%s zone=%s dispatch_ms=%s persisted=%s queued=%s",
                event_data["event_id"],
                event.event_type,
                event_data.get("zona", event_data.get("zone", "GLOBAL")),
                broadcast_ms,
                persisted,
                persistence_queued,
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


def _log_notification_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("argus_alert_task_failed error=%s", type(error).__name__)


def _persisted_event_data(event: Any, event_data: dict[str, Any]) -> dict[str, Any]:
    """Keep Gemelo actions in the event log without overwriting current occupancy."""
    persisted = copy.deepcopy(event_data)
    metadata = persisted.get("metadata") if isinstance(persisted.get("metadata"), dict) else {}
    action = any(metadata.get(field) is not None for field in ("accion", "motivo", "enviados", "withdrawals"))
    if (
        event.event_type in {"aforo", "occupancy"}
        and event.occupancy is None
        and (metadata.get("estado_actual") is False or action)
    ):
        persisted["tipo_evento"] = "aforo_action"
        persisted["event_type"] = "aforo_action"
    return persisted


async def _persist_event_background(
    event: dict[str, Any],
    alerts: list[dict[str, Any]],
    app: Any,
    rate_limiter: Any,
    should_notify_occupancy: bool,
) -> None:
    for attempt in range(3):
        try:
            await asyncio.wait_for(postgres_service.persist_event(event, alerts), timeout=4)
            latest = getattr(app.state, "latest_event", None)
            if (
                isinstance(latest, dict)
                and isinstance(latest.get("event"), dict)
                and latest["event"].get("event_id") == event.get("event_id")
                and event.get("energy_kwh") is not None
            ):
                latest["event"]["energy_kwh"] = event["energy_kwh"]
                await manager.cache_latest_event(latest)
            if should_notify_occupancy:
                notification = asyncio.create_task(
                    notify_evacuation_occupancy(rate_limiter),
                    name="argus-telegram-evacuation-count",
                )
                notification.add_done_callback(_log_notification_failure)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "telemetry_persist_retry event_id=%s attempt=%s error=%s",
                event.get("event_id"),
                attempt + 1,
                type(exc).__name__,
            )
            if attempt < 2:
                await asyncio.sleep(0.25 * (2 ** attempt))
    try:
        await postgres_service.write_error_log(
            error_type="Telemetry Persistence Failure",
            description=f"Persistence retries exhausted for event {str(event.get('event_id', ''))[:80]}",
        )
    except Exception:
        logger.exception("No se pudo registrar fallo definitivo de persistencia de telemetría")


async def close_telemetry_persistence() -> None:
    if not _persistence_tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*tuple(_persistence_tasks), return_exceptions=True), timeout=10)
    except asyncio.TimeoutError:
        logger.warning("telemetry_persistence_shutdown_timeout pending=%s", len(_persistence_tasks))
