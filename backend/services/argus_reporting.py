"""Deterministic, privacy-minimized facts for Argus chat and reports."""

from datetime import datetime, time, timedelta, timezone
import json
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import get_settings
from backend.services.camera_catalog import CAMERAS
from backend.services.door_catalog import DOORS
from backend.services.postgres_client import postgres_service


_KNOWN_ZONES = {
    "global": "GLOBAL",
    **{camera["zone"].casefold(): camera["zone"] for camera in CAMERAS},
    **{str(door["zone_name"]).casefold(): str(door["zone_name"]) for door in DOORS},
}


async def get_recent_activity(limit: int = 12) -> list[dict[str, Any]]:
    pool = postgres_service.pool
    if pool is None:
        raise RuntimeError("PostgreSQL no está disponible para Argus")
    rows = await pool.fetch(
        "SELECT received_at, event, alerts FROM security_events ORDER BY received_at DESC LIMIT $1",
        max(1, min(limit, 20)),
    )
    activities = []
    for row in rows:
        event = _json_object(row["event"])
        alerts = _json_list(row["alerts"])
        activities.append({
            "time": row["received_at"].isoformat(),
            "activity": _activity_label(str(event.get("tipo_evento") or event.get("event_type") or ""), event),
            "zone": _safe_zone(event.get("zona") or event.get("zone") or "GLOBAL"),
            "priority": _alert_priority(alerts),
        })
    return activities


async def summarize_last_days(days: int, *, pool: Any = None) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    return await summarize_window(end - timedelta(days=days), end, pool=pool)


async def summarize_previous_local_day(*, pool: Any = None) -> dict[str, Any]:
    zone = ZoneInfo(get_settings().argus_report_timezone)
    today = datetime.now(zone).date()
    previous_day = today - timedelta(days=1)
    start = datetime.combine(previous_day, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(today, time.min, tzinfo=zone).astimezone(timezone.utc)
    summary = await summarize_window(start, end, pool=pool)
    summary["report_date"] = previous_day.isoformat()
    summary["timezone"] = str(zone)
    return summary


async def summarize_window(start: datetime, end: datetime, *, pool: Any = None) -> dict[str, Any]:
    database = pool if pool is not None else postgres_service.pool
    if database is None:
        raise RuntimeError("PostgreSQL no está disponible para Argus")

    metrics = await database.fetchrow(
        """
        SELECT count(*) AS readings,
            min(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_min,
            max(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_max,
            avg(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_avg,
            min(CASE WHEN jsonb_typeof(event->'voltage_v') = 'number' THEN (event->>'voltage_v')::double precision END) AS voltage_min,
            max(CASE WHEN jsonb_typeof(event->'voltage_v') = 'number' THEN (event->>'voltage_v')::double precision END) AS voltage_max,
            count(*) FILTER (WHERE jsonb_typeof(event->'voltage_v') = 'number' AND (event->>'voltage_v')::double precision = 0) AS power_loss_events,
            max(CASE WHEN jsonb_typeof(event->'occupancy') = 'number' THEN (event->>'occupancy')::integer END) AS occupancy_peak,
            avg(CASE WHEN jsonb_typeof(event->'occupancy') = 'number' THEN (event->>'occupancy')::double precision END) AS occupancy_average,
            count(*) FILTER (WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin') AND upper(coalesce(event->>'valor', '')) IN ('GRANTED', 'DENIED', 'LOCKOUT')) AS pin_access_events,
            count(*) FILTER (WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin') AND upper(coalesce(event->>'valor', '')) = 'GRANTED') AS authorized_accesses,
            count(*) FILTER (WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin') AND upper(coalesce(event->>'valor', '')) IN ('DENIED', 'LOCKOUT')) AS denied_accesses,
            count(*) FILTER (WHERE upper(coalesce(event->'metadata'->>'access_direction', '')) IN ('ENTRY', 'ENTRADA') AND upper(coalesce(event->>'valor', '')) = 'GRANTED') AS entries,
            count(*) FILTER (WHERE upper(coalesce(event->'metadata'->>'access_direction', '')) IN ('EXIT', 'SALIDA') AND upper(coalesce(event->>'valor', '')) = 'GRANTED') AS exits,
            count(*) FILTER (WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin') AND upper(coalesce(event->>'valor', '')) = 'GRANTED' AND nullif(event->'metadata'->>'access_direction', '') IS NULL) AS accesses_without_direction,
            count(*) FILTER (WHERE jsonb_array_length(alerts) > 0) AS readings_with_alerts
        FROM security_events WHERE received_at >= $1 AND received_at < $2
        """,
        start,
        end,
    )

    last_values: dict[str, float | None] = {}
    for field in ("temperature_c", "voltage_v", "power_kw", "energy_kwh", "occupancy"):
        value = await database.fetchval(
            """
            SELECT event->>$3 FROM security_events
            WHERE received_at >= $1 AND received_at < $2
              AND jsonb_typeof(event->$3) = 'number'
            ORDER BY received_at DESC LIMIT 1
            """,
            start,
            end,
            field,
        )
        last_values[field] = _float(value)

    occupancy_rows = await database.fetch(
        """
        SELECT DISTINCT ON (zone) zone, event->>'occupancy' AS occupancy
        FROM latest_telemetry WHERE jsonb_typeof(event->'occupancy') = 'number'
        ORDER BY zone, updated_at DESC
        """
    )
    occupancy_by_zone: dict[str, int] = {}
    for row in occupancy_rows:
        zone = _safe_zone(row["zone"])
        occupancy_by_zone[zone] = occupancy_by_zone.get(zone, 0) + int(row["occupancy"])

    access_people = await database.fetchval(
        """
        SELECT count(DISTINCT details->>'target_user') FROM audit_logs
        WHERE timestamp >= $1 AND timestamp < $2
          AND action = 'PIN_ACCESS_GRANTED'
          AND nullif(details->>'target_user', '') IS NOT NULL
        """,
        start,
        end,
    )
    pin_validations = await database.fetchrow(
        """
        SELECT count(*) AS validations,
               count(DISTINCT details->>'target_user') AS distinct_people
        FROM audit_logs
        WHERE timestamp >= $1 AND timestamp < $2
          AND action = 'PIN_VALIDATED'
          AND nullif(details->>'target_user', '') IS NOT NULL
        """,
        start,
        end,
    )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "readings": int(metrics["readings"] or 0),
        "temperature_c": {
            "min": _float(metrics["temperature_min"]),
            "average": _float(metrics["temperature_avg"]),
            "max": _float(metrics["temperature_max"]),
            "last": last_values["temperature_c"],
        },
        "voltage_v": {
            "min": _float(metrics["voltage_min"]),
            "max": _float(metrics["voltage_max"]),
            "last": last_values["voltage_v"],
            "power_loss_events": int(metrics["power_loss_events"] or 0),
        },
        "power_kw_last": last_values["power_kw"],
        "energy_kwh_last": last_values["energy_kwh"],
        "occupancy": {
            "current_by_zone": occupancy_by_zone,
            "current_total": sum(occupancy_by_zone.values()) if occupancy_by_zone else None,
            "peak": metrics["occupancy_peak"],
            "average": _float(metrics["occupancy_average"]),
        },
        "access": {
            "pin_access_events": int(metrics["pin_access_events"] or 0),
            "authorized": int(metrics["authorized_accesses"] or 0),
            "denied": int(metrics["denied_accesses"] or 0),
            "entries": int(metrics["entries"] or 0),
            "exits": int(metrics["exits"] or 0),
            "without_direction": int(metrics["accesses_without_direction"] or 0),
            "pin_validations": int(pin_validations["validations"] or 0),
            "people_with_validated_pin": int(pin_validations["distinct_people"] or 0),
            "distinct_people_with_granted_pin": int(access_people or 0),
        },
        "readings_with_alerts": int(metrics["readings_with_alerts"] or 0),
    }


def format_report_facts(summary: dict[str, Any]) -> str:
    temperature = summary["temperature_c"]
    voltage = summary["voltage_v"]
    occupancy = summary["occupancy"]
    access = summary["access"]
    report_date = summary.get("report_date", "periodo seleccionado")
    return "\n".join([
        f"ARGUS · REPORTE · {report_date}",
        f"Personas presentes (último aforo por zona): {_display(occupancy['current_total'], digits=0)}",
        f"Personas con PIN validado: {access['people_with_validated_pin']} · validaciones: {access['pin_validations']}",
        f"Accesos PIN autorizados: {access['authorized']} · denegados: {access['denied']}",
        f"Entradas: {access['entries']} · salidas: {access['exits']}",
        f"Temperatura °C · mín: {_display(temperature['min'])} · media: {_display(temperature['average'])} · máx: {_display(temperature['max'])}",
        f"Voltaje V · última: {_display(voltage['last'])} · cortes: {voltage['power_loss_events']}",
        f"Potencia última kW: {_display(summary['power_kw_last'])} · energía última kWh: {_display(summary['energy_kwh_last'])}",
        f"Lecturas: {summary['readings']} · lecturas con alertas: {summary['readings_with_alerts']}",
        f"Accesos autorizados sin dirección reportada: {access['without_direction']}",
    ])


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _display(value: Any, *, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}" if value is not None else "sin lectura"


def _safe_zone(value: Any) -> str:
    if not isinstance(value, str):
        return "Otra zona"
    return _KNOWN_ZONES.get(value.strip().casefold(), "Otra zona")


def _activity_label(event_type: str, event: dict[str, Any]) -> str:
    kind = event_type.casefold()
    value = str(event.get("valor") or "").upper()
    if kind in {"acceso_pin", "access_pin"}:
        return "Acceso autorizado" if value == "GRANTED" else "Acceso denegado" if value in {"DENIED", "LOCKOUT"} else "Evento de PIN"
    if kind in {"temperatura", "temperature"}:
        return "Temperatura registrada"
    if kind in {"voltaje", "voltage"}:
        return "Corte de energía" if event.get("voltage_v") == 0 or event.get("valor") == 0 else "Voltaje registrado"
    if kind in {"aforo", "occupancy"}:
        return "Aforo actualizado"
    if kind == "camera_selected":
        return "Cámara seleccionada"
    return "Evento registrado"


def _alert_priority(alerts: list[Any]) -> str:
    severities = {str(item.get("severity", "")).lower() for item in alerts if isinstance(item, dict)}
    if "critical" in severities:
        return "critical"
    if "warning" in severities or "lockdown" in severities:
        return "warning"
    return "system"
