"""Send a fresh occupancy count to Admins while evacuation mode is active."""

import asyncio
import logging
import unicodedata
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from backend.config import get_settings
from backend.services.security_state import read_current_security_mode
from backend.services.telegram import send_telegram_message

logger = logging.getLogger("aegis.evacuation_count")


async def run_evacuation_count_report() -> None:
    settings = get_settings()
    if not settings.argus_report_database_url:
        raise RuntimeError("Falta ARGUS_REPORT_DATABASE_URL de solo lectura")
    if not settings.telegram_bot_token or not settings.authorized_telegram_users:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_USER_MAP para avisar a Admins")

    dsn = settings.argus_report_database_url.replace("postgres://", "postgresql://", 1)
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=2,
        command_timeout=15,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        mode = await read_current_security_mode(pool)
        if mode["mode"] != "EVACUACIÓN":
            logger.info("evacuation_count_skipped mode=%s", mode["mode"])
            return

        snapshot = await current_occupancy(
            pool,
            settings.evacuation_zone_names,
            settings.evacuation_occupancy_stale_after_seconds,
        )
        latest_mode = await read_current_security_mode(pool)
        if (
            latest_mode["mode"] != "EVACUACIÓN"
            or latest_mode["transition_id"] != mode["transition_id"]
        ):
            logger.info("evacuation_count_skipped reason=mode_changed_during_snapshot")
            return

        admin_usernames = sorted(set(settings.authorized_telegram_users.values()))
        admin_rows = await pool.fetch(
            """
            SELECT username FROM aegis_users
            WHERE enabled AND role = 'admin' AND username = ANY($1::text[])
            """,
            admin_usernames,
        )
        active_admins = {str(row["username"]).casefold() for row in admin_rows}
        recipients = [
            (chat_id, username)
            for chat_id, username in settings.authorized_telegram_users.items()
            if username.casefold() in active_admins
        ]
        if not recipients:
            raise RuntimeError("TELEGRAM_USER_MAP no contiene chats vinculados a cuentas Admin activas")

        message = format_evacuation_count(snapshot, settings.argus_report_timezone)
        successful_deliveries = 0
        for chat_id, username in recipients:
            try:
                await send_telegram_message(message, chat_id=str(chat_id))
                successful_deliveries += 1
            except Exception as exc:
                logger.warning("evacuation_count_send_failed user=%s error=%s", username, type(exc).__name__)
        if successful_deliveries == 0:
            raise RuntimeError("No se pudo entregar el conteo de evacuación a ningún Admin")
        logger.info(
            "evacuation_count_sent recipients=%s total=%s complete=%s",
            successful_deliveries,
            snapshot["total"],
            snapshot["complete"],
        )
    finally:
        await pool.close()


async def current_occupancy(
    pool: Any,
    expected_zones: tuple[str, ...],
    stale_after_seconds: int,
) -> dict[str, Any]:
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (zone) zone,
               (event->>'occupancy')::integer AS occupancy,
               updated_at
        FROM latest_telemetry
        WHERE lower(event_type) IN ('aforo', 'occupancy')
          AND jsonb_typeof(event->'occupancy') = 'number'
        ORDER BY zone, updated_at DESC
        """
    )
    observed = {_zone_key(str(row["zone"])): row for row in rows}
    zones = expected_zones or tuple(str(row["zone"]) for row in rows)
    now = datetime.now(timezone.utc)
    fresh: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for zone in zones:
        row = observed.get(_zone_key(zone))
        if row is None:
            unavailable.append(zone)
            continue
        updated_at = row["updated_at"].astimezone(timezone.utc)
        if (now - updated_at).total_seconds() > stale_after_seconds:
            unavailable.append(zone)
            continue
        fresh.append({"zone": zone, "occupancy": int(row["occupancy"]), "updated_at": updated_at})

    total = sum(row["occupancy"] for row in fresh) if fresh else None
    complete = bool(expected_zones) and not unavailable and len(fresh) == len(expected_zones)
    return {
        "total": total,
        "fresh": fresh,
        "unavailable": unavailable,
        "complete": complete,
        "coverage_configured": bool(expected_zones),
        "observed_at": now,
    }


def format_evacuation_count(snapshot: dict[str, Any], timezone_name: str) -> str:
    report_timezone = ZoneInfo(timezone_name)
    reported_at = snapshot["observed_at"].astimezone(report_timezone).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = ["AEGIS · ARGUS / HERMES · CONTEO DE EVACUACIÓN", "Estado: EVACUACIÓN SIMULADA ACTIVA"]
    if snapshot["total"] is None:
        lines.append("Personas por evacuar: conteo no disponible; no hay lecturas recientes.")
    elif snapshot["complete"]:
        lines.append(f"Personas por evacuar: {snapshot['total']}")
    else:
        lines.append(f"Conteo parcial de zonas con lectura reciente: {snapshot['total']}")

    lines.extend(f"• {row['zone']}: {row['occupancy']} personas" for row in snapshot["fresh"])
    if snapshot["unavailable"]:
        lines.append("Sin lectura reciente: " + ", ".join(snapshot["unavailable"][:20]))
    if not snapshot["coverage_configured"]:
        lines.append("Cobertura de zonas esperadas no configurada; el total no puede considerarse completo.")
    lines.append(f"Corte del conteo: {reported_at}")
    return "\n".join(lines)[:3900]


def _zone_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").strip()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_evacuation_count_report())


if __name__ == "__main__":
    main()
