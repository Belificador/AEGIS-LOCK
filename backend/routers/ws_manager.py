"""Authenticated dashboard WebSocket and resilient broadcast manager."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError

from backend.config import get_settings
from backend.core.security import decode_access_token
from backend.services.postgres_client import postgres_service

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.add(websocket)

    async def remove(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)

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


async def authenticate_websocket(websocket: WebSocket) -> dict[str, Any] | None:
    """Require a first-frame JWT so browser clients need not put it in the URL."""
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
        if len(raw_frame) > 8192:
            raise ValueError("Authentication frame too large")
        frame = json.loads(raw_frame)
        if not isinstance(frame, dict) or frame.get("type") != "auth":
            raise ValueError("Missing auth frame")
        token = frame.get("token")
        if not isinstance(token, str) or len(token) > 8192:
            raise ValueError("Invalid token")
        return decode_access_token(token)
    except (asyncio.TimeoutError, ValueError, JWTError, WebSocketDisconnect):
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
    await manager.add(websocket)
    try:
        await websocket.send_json({"kind": "connection", "status": "authenticated"})
        for latest_event in await postgres_service.latest_events():
            await websocket.send_json(latest_event)
        while True:
            raw_frame = await websocket.receive_text()
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
