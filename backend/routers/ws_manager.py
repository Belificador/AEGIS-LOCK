"""Authenticated dashboard WebSocket and resilient broadcast manager."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt import InvalidTokenError

from backend.config import get_settings
from backend.core.security import decode_access_token
from backend.services.postgres_client import postgres_service

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    MAX_ACTIVE_CONNECTIONS = 1000
    MAX_CONNECTIONS_PER_SUBJECT = 8

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._subjects: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

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
        for latest_event in await postgres_service.latest_events():
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
