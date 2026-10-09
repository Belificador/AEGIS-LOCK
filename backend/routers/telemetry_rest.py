"""REST telemetry ingestion for Gemelo and polling snapshots for the dashboard."""

import asyncio
import copy
import hmac
import json
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from backend.config import get_settings
from backend.core.dependencies import current_claims
from backend.core.rate_limit import limiter
from backend.core.security import decode_access_token
from backend.routers import telemetry as telemetry_websocket
from backend.routers.ws_manager import manager
from backend.services.argus_notifications import (
    notify_access_entry,
    notify_evacuation_occupancy,
    notify_security_alert,
)
from backend.services.camera_catalog import signed_camera_url
from backend.services.postgres_client import postgres_service
from backend.services.rules_engine import evaluate_event, evaluate_voltage_fluctuation
from backend.services.telemetry_ingest import parse_telemetry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telemetry", tags=["telemetry-rest"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3600/minute")
async def ingest_telemetry(
    request: Request,
    payload: Annotated[dict[str, Any], Body()],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    publisher, role = await _authenticate_publisher(authorization)
    settings = get_settings()
    try:
        payload_size = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="El evento debe ser JSON serializable") from exc
    if payload_size > settings.max_telemetry_event_bytes:
        raise HTTPException(status_code=413, detail="El evento de telemetría es demasiado grande")

    try:
        event, event_data = parse_telemetry(payload)
    except (ValueError, ValidationError) as exc:
        event_id = payload.get("event_id")
        detail = "Evento de telemetría inválido"
        if isinstance(exc, ValidationError):
            fields = sorted({
                ".".join(str(part) for part in error.get("loc", ()))
                for error in exc.errors()
                if error.get("loc")
            })
            if fields:
                detail += f"; campos inválidos: {', '.join(fields[:8])}"
        logger.warning(
            "telemetry_rest_validation_rejected publisher=%s event_id=%s reason=%s",
            publisher[:80], str(event_id or "")[:80], type(exc).__name__,
        )
        raise HTTPException(
            status_code=422,
            detail={"message": detail, "event_id": event_id if isinstance(event_id, str) else None},
        ) from exc

    metadata = event_data.get("metadata") if isinstance(event_data.get("metadata"), dict) else {}
    access_target_user = metadata.pop("target_user", None)
    event_data["metadata"] = metadata
    persisted_event_data = telemetry_websocket._persisted_event_data(event, event_data)

    if role != "gemelo-service" and event.event_type != "camera_selected":
        raise HTTPException(status_code=403, detail="La sesión del dashboard solo puede publicar selecciones de cámara")

    if event.event_type == "camera_selected":
        camera_id = str(
            payload.get("camera_id")
            or metadata.get("camera_id")
            or metadata.get("cameraId")
            or payload.get("valor")
            or ""
        )
        if not signed_camera_url(
            camera_id,
            base_url=settings.gemelo_media_base_url,
            secret=settings.telemetry_api_key or "",
            expires_at=int(time.time()) + 3600,
        ):
            raise HTTPException(status_code=404, detail="Cámara no reconocida o feed no configurado")
        event_data["camera_id"] = camera_id
        event_data["metadata"] = {**metadata, "camera_id": camera_id}
        persisted_event_data["camera_id"] = camera_id
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

    rate_limiter = getattr(request.app.state, "websocket_rate_limiter", None)
    if alerts:
        task = asyncio.create_task(
            notify_security_alert(event_data, alerts, rate_limiter),
            name="argus-telegram-alert",
        )
        task.add_done_callback(telemetry_websocket._log_notification_failure)

    if event.event_type in {"acceso_pin", "access_pin"}:
        access_value = str(payload.get("valor") or "").strip().upper()
        if access_value in {"GRANTED", "DENIED", "LOCKOUT"}:
            await postgres_service.write_audit_log(
                action="PIN_ACCESS_GRANTED" if access_value == "GRANTED" else "PIN_ACCESS_DENIED",
                performed_by=publisher,
                details={
                    "door_name": payload.get("zona", payload.get("zone", "GLOBAL")),
                    "result": access_value,
                    "pin_id": metadata.get("pin_id"),
                    "target_user": access_target_user,
                    "access_direction": metadata.get("access_direction"),
                },
            )
            if access_value == "GRANTED" and metadata.get("access_direction") == "entry":
                task = asyncio.create_task(notify_access_entry(event_data), name="argus-telegram-authorized-entry")
                task.add_done_callback(telemetry_websocket._log_notification_failure)

    live_payload = {"kind": "telemetry", "event": event_data, "alerts": alerts}
    request.app.state.latest_event = live_payload
    await manager.cache_telemetry_state(live_payload)
    await manager.cache_latest_event(live_payload)

    queued = await manager.enqueue_persistence(persisted_event_data, alerts)
    persisted = False
    if not queued and postgres_service.pool is not None:
        if len(telemetry_websocket._persistence_tasks) < telemetry_websocket._PERSISTENCE_TASK_LIMIT:
            task = asyncio.create_task(
                telemetry_websocket._persist_event_background(
                    copy.deepcopy(persisted_event_data),
                    copy.deepcopy(alerts),
                    request.app,
                    rate_limiter,
                    event.occupancy is not None,
                ),
                name=f"telemetry-rest-persist-{event.event_id}",
            )
            telemetry_websocket._persistence_tasks.add(task)
            task.add_done_callback(telemetry_websocket._persistence_tasks.discard)
            queued = True
        else:
            try:
                await asyncio.wait_for(postgres_service.persist_event(persisted_event_data, alerts), timeout=4)
                persisted = True
            except Exception:
                logger.exception("No se pudo persistir telemetría REST; cola local llena")

    logger.info(
        "telemetry_rest_accepted event_id=%s publisher=%s type=%s zone=%s persisted=%s queued=%s",
        event_data["event_id"], publisher[:80], event.event_type,
        event_data.get("zona", event_data.get("zone", "GLOBAL")), persisted, queued,
    )
    return {
        "accepted": True,
        "event_id": event_data["event_id"],
        "persisted": persisted,
        "queued_for_persistence": queued,
        "alerts": alerts,
    }


@router.get("/latest")
@limiter.limit("120/minute")
async def latest_telemetry(
    request: Request,
    _: Annotated[dict[str, Any], Depends(current_claims)],
) -> dict[str, Any]:
    states = await manager.latest_rest_telemetry()
    if not getattr(request.app.state, "telemetry_snapshot_bootstrapped", False):
        try:
            stored = await asyncio.wait_for(postgres_service.latest_events(), timeout=0.5)
            for item in stored:
                await manager.cache_telemetry_state(item, only_if_absent=True)
            states = await manager.latest_rest_telemetry()
            request.app.state.telemetry_snapshot_bootstrapped = True
        except Exception as exc:
            if not states:
                logger.warning("telemetry_rest_snapshot_bootstrap_failed error=%s", type(exc).__name__)
            request.app.state.telemetry_snapshot_bootstrapped = bool(states)
    return {"events": states, "server_time": time.time()}


async def _authenticate_publisher(authorization: str | None) -> tuple[str, str]:
    settings = get_settings()
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    token = authorization.removeprefix("Bearer ")
    if settings.telemetry_api_key and hmac.compare_digest(token, settings.telemetry_api_key):
        return "gemelo-service", "gemelo-service"

    claims = decode_access_token(token)
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="El servicio de usuarios no está disponible")
    user = await postgres_service.get_user(str(claims["sub"]))
    if user is None or user["role"] != claims.get("role"):
        raise HTTPException(status_code=401, detail="La sesión ya no está activa")
    if user["role"] not in {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="Permisos insuficientes para publicar telemetría")
    return str(user["username"]), str(user["role"])
