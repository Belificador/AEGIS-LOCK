"""Async PostgreSQL access for demo users and telemetry persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any

import asyncpg

from backend.core.passwords import hash_password


class PostgresService:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(
        self,
        database_url: str | None,
        *,
        operator_password: str | None = None,
        admin_password: str | None = None,
    ) -> None:
        if not database_url:
            return

        dsn = database_url.replace("postgres://", "postgresql://", 1)
        self.pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, command_timeout=10)
        try:
            migration = Path(__file__).resolve().parents[1] / "sql" / "001_render_postgres.sql"
            await self.pool.execute(migration.read_text(encoding="utf-8"))

            accounts = (
                ("operador", operator_password, "operator"),
                ("admin", admin_password, "admin"),
            )
            for username, password, role in accounts:
                if password:
                    await self.pool.execute(
                        """
                        INSERT INTO aegis_users (username, password_hash, role)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (username) DO UPDATE
                        SET password_hash = EXCLUDED.password_hash,
                            role = EXCLUDED.role,
                            updated_at = now()
                        """,
                        username,
                        hash_password(password),
                        role,
                    )
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def is_healthy(self) -> bool:
        if self.pool is None:
            return False
        try:
            return await self.pool.fetchval("SELECT 1") == 1
        except Exception:
            return False

    async def get_user(self, username: str) -> dict[str, str] | None:
        if self.pool is None:
            return None
        row = await self.pool.fetchrow(
            "SELECT username, password_hash, role FROM aegis_users WHERE username = $1 AND enabled",
            username,
        )
        return dict(row) if row else None

    async def issue_refresh_token(self, username: str, *, days: int) -> str:
        if self.pool is None:
            raise RuntimeError("PostgreSQL is not configured")
        token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        await self.pool.execute(
            "INSERT INTO aegis_refresh_tokens (token_hash, username, expires_at) VALUES ($1, $2, $3)",
            token_hash,
            username,
            datetime.now(timezone.utc) + timedelta(days=days),
        )
        return token

    async def rotate_refresh_token(self, token: str, *, days: int) -> tuple[str, dict[str, str]] | None:
        if self.pool is None:
            return None
        old_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        new_token = secrets.token_urlsafe(48)
        new_hash = hashlib.sha256(new_token.encode("utf-8")).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT t.username, u.role
                    FROM aegis_refresh_tokens AS t
                    JOIN aegis_users AS u ON u.username = t.username
                    WHERE t.token_hash = $1 AND t.expires_at > now() AND u.enabled
                    FOR UPDATE OF t
                    """,
                    old_hash,
                )
                if row is None:
                    return None
                await connection.execute("DELETE FROM aegis_refresh_tokens WHERE token_hash = $1", old_hash)
                await connection.execute(
                    "INSERT INTO aegis_refresh_tokens (token_hash, username, expires_at) VALUES ($1, $2, $3)",
                    new_hash,
                    row["username"],
                    datetime.now(timezone.utc) + timedelta(days=days),
                )
                user = {"username": row["username"], "role": row["role"]}
        return new_token, user

    async def revoke_refresh_token(self, token: str | None) -> None:
        if self.pool is None or not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        await self.pool.execute("DELETE FROM aegis_refresh_tokens WHERE token_hash = $1", token_hash)

    async def persist_event(self, event: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
        if self.pool is None:
            return
        event_json = json.dumps(event, separators=(",", ":"))
        alerts_json = json.dumps(alerts, separators=(",", ":"))
        event_type = str(event.get("tipo_evento") or event.get("event_type") or "telemetry")
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        is_state = metadata.get("estado_actual") is True or event_type in {
            "temperatura", "temperature", "voltaje", "voltage", "iluminacion", "aforo", "occupancy"
        } or any(
            event.get(field) is not None
            for field in ("temperature_c", "voltage_v", "power_kw", "occupancy")
        )
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO security_events (event_id, source_id, event, alerts)
                    VALUES ($1::uuid, $2, $3::jsonb, $4::jsonb)
                    """,
                    event["event_id"],
                    event["source_id"],
                    event_json,
                    alerts_json,
                )

                if is_state:
                    zone = str(event.get("zona") or event.get("zone") or "GLOBAL")
                    await connection.execute(
                        """
                        INSERT INTO latest_telemetry (source_id, event_type, zone, event, alerts, updated_at)
                        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, now())
                        ON CONFLICT (source_id, event_type, zone) DO UPDATE
                        SET event = EXCLUDED.event, alerts = EXCLUDED.alerts, updated_at = now()
                        """,
                        event["source_id"],
                        event_type,
                        zone,
                        event_json,
                        alerts_json,
                    )

    async def latest_events(self) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        rows = await self.pool.fetch("SELECT event, alerts FROM latest_telemetry ORDER BY updated_at")
        return [
            {
                "kind": "telemetry",
                "event": json.loads(row["event"]),
                "alerts": json.loads(row["alerts"]),
            }
            for row in rows
        ]


postgres_service = PostgresService()
