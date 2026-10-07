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
            migrations_dir = Path(__file__).resolve().parents[1] / "sql"
            for migration in sorted(migrations_dir.glob("*.sql")):
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

    async def revoke_refresh_token(self, token: str | None) -> str | None:
        if self.pool is None or not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return await self.pool.fetchval(
            "DELETE FROM aegis_refresh_tokens WHERE token_hash = $1 RETURNING username",
            token_hash,
        )

    async def persist_event(self, event: dict[str, Any], alerts: list[dict[str, Any]]) -> None:
        if self.pool is None:
            return
        alerts_json = json.dumps(alerts, separators=(",", ":"))
        event_type = str(event.get("tipo_evento") or event.get("event_type") or "telemetry")
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        zone = str(event.get("zona") or event.get("zone") or "GLOBAL")
        power_kw = _finite_number(event.get("power_kw"))
        supplied_energy = _finite_number(event.get("energy_kwh"))
        is_state = metadata.get("estado_actual") is True or event_type in {
            "temperatura", "temperature", "voltaje", "voltage", "iluminacion", "aforo", "occupancy"
        } or any(
            event.get(field) is not None
            for field in ("temperature_c", "voltage_v", "power_kw", "energy_kwh", "occupancy")
        )
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if power_kw is not None:
                    previous = await connection.fetchrow(
                        """
                        SELECT energy_kwh, last_power_kw, updated_at
                        FROM energy_state WHERE source_id = $1 AND zone = $2
                        FOR UPDATE
                        """,
                        event["source_id"],
                        zone,
                    )
                    now = datetime.now(timezone.utc)
                    if supplied_energy is not None:
                        energy_kwh = supplied_energy
                    elif previous is None:
                        energy_kwh = 0.0
                    else:
                        energy_kwh = integrate_energy_kwh(
                            float(previous["energy_kwh"]),
                            float(previous["last_power_kw"]),
                            previous["updated_at"],
                            now,
                        )
                    event["energy_kwh"] = round(energy_kwh, 6)
                    await connection.execute(
                        """
                        INSERT INTO energy_state (source_id, zone, energy_kwh, last_power_kw, updated_at)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (source_id, zone) DO UPDATE
                        SET energy_kwh = EXCLUDED.energy_kwh,
                            last_power_kw = EXCLUDED.last_power_kw,
                            updated_at = EXCLUDED.updated_at
                        """,
                        event["source_id"],
                        zone,
                        event["energy_kwh"],
                        power_kw,
                        now,
                    )
                elif supplied_energy is not None:
                    event["energy_kwh"] = supplied_energy

                event_json = json.dumps(event, separators=(",", ":"))
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

    async def create_temporary_pin(
        self,
        *,
        pin_id: str,
        door_name: str,
        pin_code: str,
        pin_hash: str,
        target_user: str,
        created_by: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("PostgreSQL is not configured")
        row = await self.pool.fetchrow(
            """
            INSERT INTO temporary_pins
                (id, door_name, pin_code, pin_hash, target_user, created_by, expires_at)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
            RETURNING id::text, door_name, pin_code, pin_hash, target_user,
                      created_by, expires_at, is_active, created_at
            """,
            pin_id,
            door_name,
            pin_code,
            pin_hash,
            target_user,
            created_by,
            expires_at,
        )
        return dict(row)

    async def temporary_pin_hash_exists(self, door_name: str, pin_hashes: tuple[str, ...]) -> bool:
        if self.pool is None:
            raise RuntimeError("PostgreSQL is not configured")
        result = await self.pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM temporary_pins
                WHERE door_name = $1 AND pin_hash = ANY($2::text[]) AND is_active AND expires_at > now()
            )
            """,
            door_name,
            list(pin_hashes),
        )
        return bool(result)

    async def list_temporary_pins(
        self, *, limit: int = 100, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        rows = await self.pool.fetch(
            """
            SELECT id::text, door_name, pin_code, target_user, created_by,
                   expires_at, is_active, created_at
            FROM temporary_pins
            WHERE ($1::boolean OR (is_active AND expires_at > now()))
            ORDER BY created_at DESC LIMIT $2
            """,
            include_inactive,
            limit,
        )
        return [dict(row) for row in rows]

    async def deactivate_temporary_pin(self, pin_id: str) -> dict[str, Any] | None:
        if self.pool is None:
            return None
        row = await self.pool.fetchrow(
            """
            UPDATE temporary_pins SET is_active = false
            WHERE id = $1::uuid AND is_active
            RETURNING id::text, door_name, target_user, created_by, expires_at, is_active
            """,
            pin_id,
        )
        return dict(row) if row else None

    async def validate_temporary_pin(self, door_name: str, pin_hashes: tuple[str, ...]) -> dict[str, Any] | None:
        if self.pool is None:
            return None
        row = await self.pool.fetchrow(
            """
            SELECT id::text, door_name, target_user, created_by, expires_at
            FROM temporary_pins
            WHERE door_name = $1 AND pin_hash = ANY($2::text[]) AND is_active AND expires_at > now()
            ORDER BY created_at DESC LIMIT 1
            """,
            door_name,
            list(pin_hashes),
        )
        return dict(row) if row else None

    async def write_audit_log(
        self,
        *,
        action: str,
        performed_by: str,
        details: dict[str, Any] | None = None,
    ) -> int | None:
        if self.pool is None:
            return None
        return await self.pool.fetchval(
            "INSERT INTO audit_logs (action, performed_by, details) VALUES ($1, $2, $3::jsonb) RETURNING id",
            action,
            performed_by,
            json.dumps(details or {}, separators=(",", ":")),
        )

    async def write_error_log(
        self,
        *,
        error_type: str,
        description: str,
        duration_ms: int | None = None,
    ) -> None:
        if self.pool is None:
            return
        await self.pool.execute(
            "INSERT INTO error_logs (error_type, description, duration_ms) VALUES ($1, $2, $3)",
            error_type[:80],
            description[:1200],
            max(0, duration_ms) if duration_ms is not None else None,
        )

    async def analytics_history(
        self, *, start: datetime, end: datetime, limit: int = 500
    ) -> dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("PostgreSQL is not configured")
        rows = await self.pool.fetch(
            """
            SELECT event_id::text, source_id, received_at, event
            FROM security_events
            WHERE received_at >= $1 AND received_at <= $2
            ORDER BY received_at DESC LIMIT $3
            """,
            start,
            end,
            limit,
        )
        samples: list[dict[str, Any]] = []
        peaks: dict[str, dict[str, Any] | None] = {
            "temperature": None,
            "power": None,
            "energy": None,
        }
        for name, field, unit in (
            ("temperature", "temperature_c", "°C"),
            ("power", "power_kw", "kW"),
            ("energy", "energy_kwh", "kWh"),
        ):
            peak_row = await self.pool.fetchrow(
                """
                SELECT event_id::text, source_id, received_at, event,
                       (event->>$3)::double precision AS metric_value
                FROM security_events
                WHERE received_at >= $1 AND received_at <= $2
                  AND jsonb_typeof(event->$3) = 'number'
                ORDER BY (event->>$3)::double precision DESC
                LIMIT 1
                """,
                start,
                end,
                field,
            )
            if peak_row is not None:
                peak_event = json.loads(peak_row["event"])
                peaks[name] = {
                    "value": float(peak_row["metric_value"]),
                    "unit": unit,
                    "zone": peak_event.get("zona") or peak_event.get("zone") or "GLOBAL",
                    "timestamp": peak_row["received_at"].isoformat(),
                    "event_id": peak_row["event_id"],
                }

        for row in reversed(rows):
            event = json.loads(row["event"])
            sample = {
                "event_id": row["event_id"],
                "source_id": row["source_id"],
                "timestamp": row["received_at"].isoformat(),
                "zone": event.get("zona") or event.get("zone") or "GLOBAL",
                "temperature_c": _finite_number(event.get("temperature_c")),
                "power_kw": _finite_number(event.get("power_kw")),
                "energy_kwh": _finite_number(event.get("energy_kwh")),
            }
            samples.append(sample)

        audits = await self.pool.fetch(
            """
            SELECT id, action, performed_by, timestamp, details
            FROM audit_logs WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp DESC LIMIT 100
            """,
            start,
            end,
        )
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "samples": samples,
            "peaks": peaks,
            "audit_logs": [
                {
                    "id": row["id"],
                    "action": row["action"],
                    "performed_by": row["performed_by"],
                    "timestamp": row["timestamp"].isoformat(),
                    "details": json.loads(row["details"]),
                }
                for row in audits
            ],
        }

    async def error_history(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if self.pool is None:
            raise RuntimeError("PostgreSQL is not configured")
        total = await self.pool.fetchval("SELECT count(*) FROM error_logs")
        rows = await self.pool.fetch(
            """
            SELECT id, error_type, description, timestamp, duration_ms
            FROM error_logs ORDER BY timestamp DESC LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "errors": [
                {
                    "id": row["id"],
                    "error_type": row["error_type"],
                    "description": row["description"],
                    "timestamp": row["timestamp"].isoformat(),
                    "duration_ms": row["duration_ms"],
                }
                for row in rows
            ],
        }

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


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _peak(sample: dict[str, Any], key: str, unit: str) -> dict[str, Any]:
    return {
        "value": sample[key],
        "unit": unit,
        "zone": sample["zone"],
        "timestamp": sample["timestamp"],
        "event_id": sample["event_id"],
    }


def integrate_energy_kwh(
    previous_energy_kwh: float,
    previous_power_kw: float,
    previous_updated_at: datetime,
    now: datetime,
) -> float:
    """Integrate the last simulated power state over the elapsed interval."""
    elapsed_hours = max(0.0, (now - previous_updated_at).total_seconds() / 3600)
    return previous_energy_kwh + previous_power_kw * elapsed_hours
