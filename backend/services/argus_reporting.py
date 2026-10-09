"""Deterministic, privacy-minimized report aggregates for Argus."""

import asyncio
import json
import re
from datetime import datetime, time, timedelta, timezone
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


async def get_current_building_mode(*, pool: Any = None) -> dict[str, Any]:
    database = pool if pool is not None else postgres_service.pool
    if database is None:
        raise RuntimeError("PostgreSQL no está disponible para Argus")
    row = await database.fetchrow(
        """
        SELECT id, action, timestamp, performed_by
        FROM audit_logs
        WHERE action IN (
            'LOCKDOWN_ACTIVATED', 'LOCKDOWN_RELEASED',
            'EVACUATION_ACTIVATED', 'EVACUATION_RELEASED'
        )
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if row is None:
        return {"mode": "NORMAL", "event_id": None, "updated_at": None, "actor": None}
    mode_by_action = {
        "LOCKDOWN_ACTIVATED": "LOCKDOWN",
        "EVACUATION_ACTIVATED": "EVACUACIÓN",
        "LOCKDOWN_RELEASED": "NORMAL",
        "EVACUATION_RELEASED": "NORMAL",
    }
    return {
        "mode": mode_by_action.get(row["action"], "NORMAL"),
        "event_id": int(row["id"]),
        "updated_at": row["timestamp"].isoformat(),
        "actor": row["performed_by"],
    }


async def get_current_occupancy(*, pool: Any = None, max_age_seconds: int = 300) -> dict[str, Any]:
    database = pool if pool is not None else postgres_service.pool
    if database is None:
        raise RuntimeError("PostgreSQL no está disponible para Argus")
    rows = await database.fetch(
        """
        SELECT DISTINCT ON (zone) zone, event->>'occupancy' AS occupancy, updated_at
        FROM latest_telemetry
        WHERE jsonb_typeof(event->'occupancy') = 'number'
        ORDER BY zone, updated_at DESC
        """
    )
    now = datetime.now(timezone.utc)
    fresh_by_zone: dict[str, int] = {}
    timestamps: list[datetime] = []
    stale_zones: list[str] = []
    for row in rows:
        updated_at = row["updated_at"]
        if (now - updated_at).total_seconds() > max_age_seconds:
            stale_zones.append(_safe_zone(row["zone"]))
            continue
        zone = _safe_zone(row["zone"])
        fresh_by_zone[zone] = fresh_by_zone.get(zone, 0) + int(row["occupancy"])
        timestamps.append(updated_at)

    is_stale = not rows or bool(stale_zones)
    return {
        "total": sum(fresh_by_zone.values()) if fresh_by_zone and not is_stale else None,
        "by_zone": fresh_by_zone,
        "updated_at": min(timestamps).isoformat() if timestamps else None,
        "stale": is_stale,
        "stale_zones": sorted(set(stale_zones)),
    }


async def summarize_last_days(days: int, *, pool: Any = None) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return await summarize_window(start, end, pool=pool)


async def get_recent_activity(limit: int = 12) -> list[dict[str, Any]]:
    pool = postgres_service.pool
    if pool is None:
        raise RuntimeError("PostgreSQL no está disponible para Argus")
    limit = max(1, min(limit, 20))
    telemetry_rows, audit_rows, error_rows = await asyncio.gather(
        pool.fetch(
            "SELECT received_at, event, alerts FROM security_events ORDER BY received_at DESC LIMIT $1",
            limit,
        ),
        pool.fetch(
            "SELECT timestamp, action, details FROM audit_logs ORDER BY timestamp DESC LIMIT $1",
            limit,
        ),
        pool.fetch(
            "SELECT timestamp, error_type FROM error_logs ORDER BY timestamp DESC LIMIT $1",
            limit,
        ),
    )

    activity: list[tuple[datetime, dict[str, Any]]] = []
    for row in telemetry_rows:
        event = row["event"]
        if isinstance(event, str):
            event = json.loads(event)
        event_type = str(event.get("tipo_evento") or event.get("event_type") or "telemetry")
        zone = _safe_zone(event.get("zona") or event.get("zone") or "GLOBAL")
        value = event.get("valor")
        alerts = row["alerts"]
        if isinstance(alerts, str):
            alerts = json.loads(alerts)
        timestamp = row["received_at"]
        activity.append((timestamp, {
            "time": timestamp.isoformat(),
            "activity": _activity_label(event_type, value, event),
            "zone": zone,
            "priority": _alert_priority(alerts),
        }))

    for row in audit_rows:
        timestamp = row["timestamp"]
        details = row["details"]
        if isinstance(details, str):
            details = json.loads(details)
        details = details if isinstance(details, dict) else {}
        action = str(row["action"])
        activity.append((timestamp, {
            "time": timestamp.isoformat(),
            "activity": _audit_activity_label(action),
            "zone": _safe_zone(details.get("zone") or details.get("zona") or "GLOBAL"),
            "priority": "critical" if action in {"PIN_ACCESS_DENIED", "LOGIN_FAILED", "REFRESH_REJECTED"} else "system",
        }))

    for row in error_rows:
        timestamp = row["timestamp"]
        error_type = _safe_error_type(row["error_type"])
        activity.append((timestamp, {
            "time": timestamp.isoformat(),
            "activity": f"Error de sistema · {error_type}",
            "zone": "GLOBAL",
            "priority": "warning",
        }))

    activity.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in activity[:limit]]


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
        SELECT
            count(*) AS readings,
            min(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_min,
            max(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_max,
            avg(CASE WHEN jsonb_typeof(event->'temperature_c') = 'number' THEN (event->>'temperature_c')::double precision END) AS temperature_avg,
            min(CASE WHEN jsonb_typeof(event->'voltage_v') = 'number' THEN (event->>'voltage_v')::double precision END) AS voltage_min,
            max(CASE WHEN jsonb_typeof(event->'voltage_v') = 'number' THEN (event->>'voltage_v')::double precision END) AS voltage_max,
            count(*) FILTER (WHERE jsonb_typeof(event->'voltage_v') = 'number' AND (event->>'voltage_v')::double precision = 0) AS power_loss_events,
            max(CASE WHEN jsonb_typeof(event->'occupancy') = 'number' THEN (event->>'occupancy')::integer END) AS occupancy_peak,
            avg(CASE WHEN jsonb_typeof(event->'occupancy') = 'number' THEN (event->>'occupancy')::double precision END) AS occupancy_average,
            count(*) FILTER (
                WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin')
                  AND upper(coalesce(event->>'valor', '')) IN ('GRANTED', 'DENIED', 'LOCKOUT')
            ) AS pin_access_events,
            count(*) FILTER (
                WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin')
                  AND upper(coalesce(event->>'valor', '')) = 'GRANTED'
            ) AS authorized_accesses,
            count(*) FILTER (
                WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin')
                  AND upper(coalesce(event->>'valor', '')) IN ('DENIED', 'LOCKOUT')
            ) AS denied_accesses,
            count(*) FILTER (
                WHERE upper(coalesce(event->'metadata'->>'access_direction', '')) IN ('ENTRY', 'ENTRADA')
                  AND upper(coalesce(event->>'valor', '')) = 'GRANTED'
            ) AS entries,
            count(*) FILTER (
                WHERE upper(coalesce(event->'metadata'->>'access_direction', '')) IN ('EXIT', 'SALIDA')
                  AND upper(coalesce(event->>'valor', '')) = 'GRANTED'
            ) AS exits,
            count(*) FILTER (
                WHERE lower(coalesce(event->>'tipo_evento', event->>'event_type', '')) IN ('acceso_pin', 'access_pin')
                  AND upper(coalesce(event->>'valor', '')) = 'GRANTED'
                  AND nullif(event->'metadata'->>'access_direction', '') IS NULL
            ) AS accesses_without_direction,
            count(*) FILTER (WHERE jsonb_array_length(alerts) > 0) AS readings_with_alerts
        FROM security_events
        WHERE received_at >= $1 AND received_at < $2
        """,
        start,
        end,
    )

    last_values: dict[str, Any] = {}
    for field in ("temperature_c", "voltage_v", "power_kw", "energy_kwh", "occupancy"):
        last_values[field] = await database.fetchval(
            """
            SELECT event->>$3
            FROM security_events
            WHERE received_at >= $1 AND received_at < $2
              AND jsonb_typeof(event->$3) = 'number'
            ORDER BY received_at DESC LIMIT 1
            """,
            start,
            end,
            field,
        )

    occupancy_rows = await database.fetch(
        """
        SELECT DISTINCT ON (zone) zone, event->>'occupancy' AS occupancy
        FROM latest_telemetry
        WHERE jsonb_typeof(event->'occupancy') = 'number'
        ORDER BY zone, updated_at DESC
        """
    )
    occupancy_by_zone: dict[str, int] = {}
    for row in occupancy_rows:
        safe_zone = _safe_zone(row["zone"])
        occupancy_by_zone[safe_zone] = occupancy_by_zone.get(safe_zone, 0) + int(row["occupancy"])
    access_people = await database.fetchval(
        """
        SELECT count(DISTINCT details->>'target_user')
        FROM audit_logs
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
            "last": _float(last_values["temperature_c"]),
        },
        "voltage_v": {
            "min": _float(metrics["voltage_min"]),
            "max": _float(metrics["voltage_max"]),
            "last": _float(last_values["voltage_v"]),
            "power_loss_events": int(metrics["power_loss_events"] or 0),
        },
        "power_kw_last": _float(last_values["power_kw"]),
        "energy_kwh_last": _float(last_values["energy_kwh"]),
        "occupancy": {
            "current_by_zone": occupancy_by_zone,
            "current_total": sum(occupancy_by_zone.values()) if occupancy_by_zone else None,
            "peak": metrics["occupancy_peak"],
            "average": _float(metrics["occupancy_average"]),
        },
        "access": {
            "pin_validations": int(pin_validations["validations"] or 0),
            "people_with_validated_pin": int(pin_validations["distinct_people"] or 0),
            "pin_access_events": int(metrics["pin_access_events"] or 0),
            "authorized": int(metrics["authorized_accesses"] or 0),
            "denied": int(metrics["denied_accesses"] or 0),
            "entries": int(metrics["entries"] or 0),
            "exits": int(metrics["exits"] or 0),
            "without_direction": int(metrics["accesses_without_direction"] or 0),
            "distinct_people_with_granted_pin": int(access_people or 0),
        },
        "readings_with_alerts": int(metrics["readings_with_alerts"] or 0),
    }


def format_report_facts(summary: dict[str, Any]) -> str:
    temperature = summary["temperature_c"]
    voltage = summary["voltage_v"]
    occupancy = summary["occupancy"]
    access = summary["access"]
    lines = [
        f"ARGUS · REPORTE DIARIO · {summary.get('report_date', 'periodo seleccionado')}",
        f"Personas presentes (último aforo por zona): {occupancy['current_total'] if occupancy['current_total'] is not None else 'sin lectura'}",
        f"Personas distintas con PIN validado: {access['people_with_validated_pin']} · validaciones: {access['pin_validations']}",
        f"Accesos PIN autorizados: {access['authorized']} · denegados: {access['denied']}",
        f"Entradas: {access['entries']} · salidas: {access['exits']}",
        f"Temperatura °C · mín: {_display(temperature['min'])} · media: {_display(temperature['average'])} · máx: {_display(temperature['max'])}",
        f"Voltaje V · última: {_display(voltage['last'])} · cortes: {voltage['power_loss_events']}",
        f"Potencia última kW: {_display(summary['power_kw_last'])} · energía última kWh: {_display(summary['energy_kwh_last'])}",
        f"Lecturas: {summary['readings']} · lecturas con alertas: {summary['readings_with_alerts']}",
    ]
    if access["without_direction"]:
        lines.append(f"Sin dirección entrada/salida reportada: {access['without_direction']} accesos autorizados")
    return "\n".join(lines)


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _display(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "sin lectura"


def _safe_zone(value: Any) -> str:
    if not isinstance(value, str):
        return "Otra zona"
    return _KNOWN_ZONES.get(value.strip().casefold(), "Otra zona")


def _activity_label(event_type: str, value: Any, event: dict[str, Any]) -> str:
    kind = event_type.lower()
    result = str(value or "").upper()
    if kind == "aforo_action":
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        action = metadata.get("accion") or metadata.get("motivo")
        return f"Acción del modelo · {action}" if isinstance(action, str) else "Acción de aforo registrada"
    if kind in {"acceso_pin", "access_pin"}:
        return "Acceso autorizado" if result == "GRANTED" else "Acceso denegado" if result in {"DENIED", "LOCKOUT"} else "Evento de PIN"
    if kind in {"temperatura", "temperature"}:
        return "Temperatura registrada"
    if kind in {"voltaje", "voltage"}:
        return "Corte de energía" if event.get("voltage_v") == 0 else "Voltaje registrado"
    if kind in {"iluminacion", "illumination", "lighting"}:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        value = event.get("valor")
        if value is None and metadata.get("factor_electrico") is not None:
            value = float(metadata["factor_electrico"]) * 100
        try:
            percentage = float(value)
        except (TypeError, ValueError):
            return "Iluminación actualizada"
        return f"Iluminación actualizada: {percentage:g} %" if 0 <= percentage <= 100 else "Iluminación actualizada"
    if kind in {"aforo", "occupancy"}:
        return "Aforo actualizado"
    if kind == "camera_selected":
        return "Cámara seleccionada"
    if kind in {"movimiento", "movement", "motion", "motion_detected", "movimiento_detectado"}:
        return "Movimiento detectado"
    return "Evento registrado"


def _alert_priority(alerts: Any) -> str:
    if not isinstance(alerts, list):
        return "system"
    severities = {str(alert.get("severity", "")).lower() for alert in alerts if isinstance(alert, dict)}
    if "critical" in severities:
        return "critical"
    if "lockdown" in severities or "warning" in severities:
        return "warning"
    return "system"


def _audit_activity_label(action: str) -> str:
    labels = {
        "PIN_ACCESS_GRANTED": "Acceso autorizado",
        "PIN_ACCESS_DENIED": "Acceso denegado",
        "PIN_VALIDATED": "PIN validado",
        "PIN_VALIDATION_DENIED": "PIN rechazado",
        "PIN_GENERATED": "PIN temporal generado",
        "PIN_REVOKED": "PIN temporal revocado",
        "LOGIN_SUCCEEDED": "Inicio de sesión correcto",
        "LOGIN_FAILED": "Inicio de sesión rechazado",
        "LOGOUT": "Cierre de sesión",
        "REFRESH_REJECTED": "Renovación de sesión rechazada",
        "LOCKDOWN_ACTIVATED": "Lockdown activado",
        "LOCKDOWN_RELEASED": "Lockdown liberado",
        "EVACUATION_ACTIVATED": "Evacuación activada",
        "EVACUATION_RELEASED": "Evacuación liberada",
        "ALARM_ACKNOWLEDGED": "Alerta acusada recibo",
        "CAMERA_SELECTED": "Cámara seleccionada",
        "ARGUS_REPORT_SENT_TELEGRAM": "Informe de Argus enviado",
    }
    return labels.get(action, "Acción de seguridad registrada")


def _safe_error_type(value: Any) -> str:
    if not isinstance(value, str):
        return "Error de sistema"
    normalized = value.strip()[:80]
    if not normalized or not re.fullmatch(r"[A-Za-z0-9 _.-]+", normalized):
        return "Error de sistema"
    return normalized
