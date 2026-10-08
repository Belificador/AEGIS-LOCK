"""Authenticated dashboard WebSocket and resilient broadcast manager."""

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt import InvalidTokenError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from backend.config import get_settings
from backend.core.security import decode_access_token
from backend.services.argus_notifications import notify_evacuation_occupancy
from backend.services.postgres_client import postgres_service

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    MAX_ACTIVE_CONNECTIONS = 1000
    MAX_CONNECTIONS_PER_SUBJECT = 8

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._subjects: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()
        self._redis: Redis | None = None
        self._pubsub: Any = None
        self._pubsub_task: asyncio.Task[None] | None = None
        self._persistence_task: asyncio.Task[None] | None = None
        self._rate_limiter: Any = None
        self._consumer = f"api-{id(self):x}"
        self._channel = "aegis:telemetry:live:v1"
        self._latest_key = "aegis:telemetry:latest:v1"
        self._stream = "aegis:telemetry:persist:v1"
        self._stream_group = "aegis-telemetry-persistence"

    async def start(self, storage_uri: str | None, rate_limiter: Any = None) -> None:
        if not storage_uri or not storage_uri.startswith(("redis://", "rediss://")):
            return
        try:
            self._redis = Redis.from_url(storage_uri, decode_responses=True)
            self._rate_limiter = rate_limiter
            try:
                await self._redis.xgroup_create(self._stream, self._stream_group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._channel)
            self._pubsub_task = asyncio.create_task(self._listen_for_broadcasts(), name="aegis-telemetry-pubsub")
            self._persistence_task = asyncio.create_task(self._consume_persistence_stream(), name="aegis-telemetry-persistence")
            logger.info("telemetry_pubsub_started")
        except Exception:
            logger.exception("telemetry_pubsub_start_failed; using local websocket broadcast")
            await self.close()

    async def close(self) -> None:
        for attribute in ("_pubsub_task", "_persistence_task"):
            task = getattr(self, attribute)
            setattr(self, attribute, None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enqueue_persistence(self, event: dict[str, Any], alerts: list[dict[str, Any]]) -> bool:
        if self._redis is None:
            return False
        try:
            await self._redis.xadd(self._stream, {
                "event": json.dumps(event, separators=(",", ":"), default=str),
                "alerts": json.dumps(alerts, separators=(",", ":"), default=str),
            })
            return True
        except Exception:
            logger.exception("telemetry_persistence_enqueue_failed; using local retry queue")
            return False

    async def _consume_persistence_stream(self) -> None:
        while True:
            try:
                claimed = await self._redis.xautoclaim(
                    self._stream,
                    self._stream_group,
                    self._consumer,
                    min_idle_time=30_000,
                    start_id="0-0",
                    count=20,
                )
                messages = claimed[1] if isinstance(claimed, (tuple, list)) and len(claimed) > 1 else []
                await self._persist_stream_messages(messages)
                batches = await self._redis.xreadgroup(
                    self._stream_group,
                    self._consumer,
                    streams={self._stream: ">"},
                    count=20,
                    block=1000,
                )
                for _stream_name, batch in batches or []:
                    await self._persist_stream_messages(batch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telemetry_persistence_stream_failed")
                await asyncio.sleep(1)

    async def _persist_stream_messages(self, messages: list[Any]) -> None:
        for stream_id, fields in messages:
            try:
                event = json.loads(fields["event"])
                alerts = json.loads(fields["alerts"])
                if postgres_service.pool is None:
                    raise RuntimeError("PostgreSQL is unavailable; keep telemetry queued")
                if await self._event_already_persisted(event.get("event_id")):
                    await self._redis.xack(self._stream, self._stream_group, stream_id)
                    continue
                for attempt in range(3):
                    try:
                        await asyncio.wait_for(postgres_service.persist_event(event, alerts), timeout=4)
                        await self._redis.xack(self._stream, self._stream_group, stream_id)
                        if event.get("energy_kwh") is not None:
                            latest = await self.latest_cached_event()
                            latest_event = latest.get("event") if isinstance(latest, dict) else None
                            if isinstance(latest_event, dict) and latest_event.get("event_id") == event.get("event_id"):
                                latest_event["energy_kwh"] = event["energy_kwh"]
                                await self.cache_latest_event(latest)
                        if event.get("occupancy") is not None and self._rate_limiter is not None:
                            notification = asyncio.create_task(
                                notify_evacuation_occupancy(self._rate_limiter),
                                name="argus-telegram-evacuation-count",
                            )
                            notification.add_done_callback(_log_stream_notification_failure)
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if await self._event_already_persisted(event.get("event_id")):
                            await self._redis.xack(self._stream, self._stream_group, stream_id)
                            break
                        logger.warning(
                            "telemetry_stream_persist_retry event_id=%s attempt=%s error=%s",
                            str(event.get("event_id", ""))[:80],
                            attempt + 1,
                            type(exc).__name__,
                        )
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.25 * (2 ** attempt))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Leave failed stream entries pending; a worker reclaims and retries them.
                logger.exception("telemetry_stream_entry_pending stream_id=%s", stream_id)

    async def _event_already_persisted(self, event_id: Any) -> bool:
        if not event_id or postgres_service.pool is None:
            return False
        return bool(await postgres_service.pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM security_events WHERE event_id = $1::uuid)",
            event_id,
        ))

    async def _listen_for_broadcasts(self) -> None:
        while True:
            try:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                payload = json.loads(message["data"])
                if isinstance(payload, dict):
                    await self._broadcast_local(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telemetry_pubsub_receive_failed")
                await asyncio.sleep(0.5)

    async def add(self, websocket: WebSocket, subject: str) -> bool:
        async with self._lock:
            if len(self.active_connections) >= self.MAX_ACTIVE_CONNECTIONS:
                return False
            if sum(value == subject for value in self._subjects.values()) >= self.MAX_CONNECTIONS_PER_SUBJECT:
                return False
            self.active_connections.add(websocket)
            self._subjects[websocket] = subject
            return True

    async def remove(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)
            self._subjects.pop(websocket, None)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if self._redis is not None:
            try:
                await self.cache_latest_event(message)
            except Exception:
                logger.exception("telemetry_latest_cache_write_failed")
            try:
                subscribers = await self._redis.publish(self._channel, json.dumps(message, separators=(",", ":"), default=str))
                if subscribers:
                    return
            except Exception:
                logger.exception("telemetry_pubsub_publish_failed; using local websocket broadcast")
        await self._broadcast_local(message)

    async def cache_latest_event(self, message: dict[str, Any]) -> None:
        if self._redis is None:
            return
        cached = json.loads(json.dumps(message, separators=(",", ":"), default=str))
        event = cached.get("event") if isinstance(cached, dict) else None
        if isinstance(event, dict) and isinstance(event.get("metadata"), dict):
            event["metadata"].pop("feed_url", None)
        await self._redis.set(self._latest_key, json.dumps(cached, separators=(",", ":")), ex=300)

    async def latest_cached_event(self) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            cached = await self._redis.get(self._latest_key)
            value = json.loads(cached) if cached else None
            return value if isinstance(value, dict) else None
        except Exception:
            logger.exception("telemetry_latest_cache_read_failed")
            return None

    async def _broadcast_local(self, message: dict[str, Any]) -> None:
        async with self._lock:
            clients = tuple(self.active_connections)
        if not clients:
            return
        results = await asyncio.gather(
            *(asyncio.wait_for(client.send_json(message), timeout=2) for client in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, Exception):
                await self.remove(client)
                try:
                    await client.close(code=1011)
                except Exception:
                    pass
                try:
                    await postgres_service.write_error_log(
                        error_type="WebSocket Disconnect",
                        description="Dashboard socket timed out during telemetry broadcast",
                    )
                except Exception:
                    logger.exception("No se pudo guardar el timeout del dashboard")

manager = ConnectionManager()
logger = logging.getLogger(__name__)


def _log_stream_notification_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("argus_evacuation_count_task_failed error=%s", type(error).__name__)


async def authenticate_websocket(websocket: WebSocket, *, purpose: str = "dashboard") -> dict[str, Any] | None:
    """Require a first-frame JWT so browser clients need not put it in the URL."""
    client_ip = websocket.client.host if websocket.client else "unknown"
    rate_limiter = getattr(websocket.app.state, "websocket_rate_limiter", None)
    if rate_limiter is not None:
        try:
            if not await rate_limiter.allow(f"ip:{client_ip}", f"{purpose}-auth", limit=20, window_seconds=60):
                await _safe_close(websocket, code=4429, reason="Rate limit exceeded")
                return None
        except Exception:
            logger.exception("No se pudo consultar el rate limiter compartido del WebSocket")
            await _safe_close(websocket, code=1013, reason="Rate limiter unavailable")
            return None
    origin = websocket.headers.get("origin")
    if origin and origin not in get_settings().allowed_origins:
        try:
            await postgres_service.write_error_log(
                error_type="403 Forbidden",
                description=f"WebSocket origin rejected on {websocket.url.path}",
            )
        except Exception:
            logger.exception("No se pudo guardar el 403 de WebSocket")
        await _safe_close(websocket, code=4403, reason="Origin not allowed")
        return None
    await websocket.accept()
    try:
        raw_frame = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw_frame.encode("utf-8")) > 8192:
            raise ValueError("Authentication frame too large")
        frame = json.loads(raw_frame)
        if not isinstance(frame, dict) or frame.get("type") != "auth":
            raise ValueError("Missing auth frame")
        token = frame.get("token")
        if not isinstance(token, str) or len(token) > 8192:
            raise ValueError("Invalid token")
        claims = decode_access_token(token)
    except (asyncio.TimeoutError, ValueError, InvalidTokenError, WebSocketDisconnect):
        try:
            await postgres_service.write_error_log(
                error_type="WebSocket Authentication Failure",
                description=f"Auth frame rejected on {websocket.url.path}",
            )
        except Exception:
            logger.exception("No se pudo guardar el error de autenticación WebSocket")
        await _safe_close(websocket, code=4401, reason="Authentication required")
        return None
    except Exception:
        try:
            await postgres_service.write_error_log(
                error_type="WebSocket Authentication Failure",
                description=f"Unexpected auth error on {websocket.url.path}",
            )
        except Exception:
            logger.exception("No se pudo guardar el error de autenticación WebSocket")
        await _safe_close(websocket, code=4401, reason="Authentication required")
        return None

    if postgres_service.pool is None:
        await _safe_close(websocket, code=1013, reason="User service unavailable")
        return None
    try:
        user = await postgres_service.get_user(str(claims["sub"]))
    except Exception:
        logger.exception("No se pudo comprobar el estado de la cuenta en el WebSocket")
        await _safe_close(websocket, code=1013, reason="User service unavailable")
        return None
    if user is None or user["role"] != claims.get("role"):
        try:
            await postgres_service.write_error_log(
                error_type="WebSocket Authentication Failure",
                description=f"Disabled or changed account rejected on {websocket.url.path}",
            )
        except Exception:
            logger.exception("No se pudo guardar la cuenta revocada del WebSocket")
        await _safe_close(websocket, code=4401, reason="Authentication required")
        return None
    claims["username"] = user["username"]
    return claims


async def _safe_close(websocket: WebSocket, *, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


@router.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket) -> None:
    claims = await authenticate_websocket(websocket)
    if claims is None:
        return
    started = time.monotonic()
    if not await manager.add(websocket, str(claims["sub"])):
        await _safe_close(websocket, code=4429, reason="Connection limit exceeded")
        return
    try:
        await websocket.send_json({"kind": "connection", "status": "authenticated"})
        cached_event = await manager.latest_cached_event() or getattr(websocket.app.state, "latest_event", None)
        cached_data = cached_event.get("event") if isinstance(cached_event, dict) else None
        cached_signature = (
            cached_data.get("source_id"),
            cached_data.get("zone") or cached_data.get("zona"),
            cached_data.get("event_type") or cached_data.get("tipo_evento"),
        ) if isinstance(cached_data, dict) else None
        seen_event_ids: set[str] = set()
        if cached_event:
            cached_id = str((cached_event.get("event") or {}).get("event_id"))
            if cached_id:
                seen_event_ids.add(cached_id)
            await websocket.send_json(cached_event)
        for latest_event in await postgres_service.latest_events():
            latest_data = latest_event.get("event")
            if not isinstance(latest_data, dict):
                continue
            latest_id = str(latest_data.get("event_id") or "")
            if latest_id and latest_id in seen_event_ids:
                continue
            signature = (
                latest_data.get("source_id"),
                latest_data.get("zone") or latest_data.get("zona"),
                latest_data.get("event_type") or latest_data.get("tipo_evento"),
            )
            if cached_signature and signature == cached_signature:
                continue
            await websocket.send_json(latest_event)
        while True:
            if time.time() >= int(claims["exp"]):
                await _safe_close(websocket, code=4401, reason="Access token expired")
                break
            try:
                raw_frame = await asyncio.wait_for(websocket.receive_text(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if len(raw_frame.encode("utf-8")) > 8192:
                await _safe_close(websocket, code=1009, reason="Frame too large")
                break
            rate_limiter = getattr(websocket.app.state, "websocket_rate_limiter", None)
            if rate_limiter is not None:
                try:
                    client_ip = websocket.client.host if websocket.client else "unknown"
                    if not await rate_limiter.allow(f"ip:{client_ip}", "dashboard-frame", limit=240, window_seconds=60):
                        await _safe_close(websocket, code=4429, reason="Rate limit exceeded")
                        break
                except Exception:
                    logger.exception("No se pudo consultar el rate limiter de frames WebSocket")
                    await _safe_close(websocket, code=1013, reason="Rate limiter unavailable")
                    break
            try:
                frame = json.loads(raw_frame)
            except ValueError:
                continue
            if isinstance(frame, dict) and frame.get("type") == "ping":
                ping_id = str(frame.get("id") or "")[:64]
                if ping_id:
                    await websocket.send_json({
                        "kind": "heartbeat",
                        "type": "pong",
                        "id": ping_id,
                        "server_time": int(time.time() * 1000),
                    })
    except WebSocketDisconnect as exc:
        if exc.code not in {1000, 1001}:
            try:
                await postgres_service.write_error_log(
                    error_type="WebSocket Disconnect",
                    description=f"/ws/dashboard closed with code {exc.code}",
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
            except Exception:
                logger.exception("No se pudo guardar la desconexión del dashboard")
    except Exception:
        try:
            await postgres_service.write_error_log(
                error_type="WebSocket Error",
                description="/ws/dashboard terminated by server error",
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        except Exception:
            logger.exception("No se pudo guardar el error del dashboard")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await manager.remove(websocket)
