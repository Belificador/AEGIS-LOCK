from backend.services.argus_reporting import _activity_label
from backend.routers.telemetry import _persisted_event_data
from backend.services.telemetry_ingest import parse_telemetry


def test_gemelo_lighting_envelope_preserves_zero_percent_and_zone_metadata() -> None:
    event, event_data = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "iluminacion",
        "zona": "Administración",
        "valor": 0,
        "metadata": {
            "zona_id": 3,
            "unidad": "%",
            "factor_electrico": 0,
            "voltaje_v": 0,
            "estado": "blackout",
            "alcance": "zona",
            "estado_actual": True,
        },
    })

    assert event.event_type == "iluminacion"
    assert event_data["valor"] == 0
    assert event_data["metadata"]["zona_id"] == 3
    assert event_data["metadata"]["factor_electrico"] == 0
    assert _activity_label("iluminacion", 0, event_data) == "Iluminación actualizada: 0 %"


def test_gemelo_zero_occupancy_is_a_real_state_not_a_missing_value() -> None:
    event, event_data = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "aforo",
        "zona": "Todas",
        "valor": 0,
        "metadata": {"alcance": "global", "estado_actual": True, "snapshot_inicial": True},
    })

    assert event.occupancy == 0
    assert event_data["occupancy"] == 0


def test_gemelo_occupancy_action_does_not_replace_the_current_count() -> None:
    event, event_data = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "aforo",
        "zona": "Todas",
        "valor": 0,
        "metadata": {
            "accion": "mover",
            "enviados": 1,
            "ids": ["persona-1"],
            "punto": [1.25, 0, -3.5],
            "max": 40,
        },
    })

    assert event.occupancy is None
    assert event_data["valor"] == 0
    persisted = _persisted_event_data(event, event_data)
    assert event_data["tipo_evento"] == "aforo"
    assert persisted["tipo_evento"] == "aforo_action"
    assert persisted["event_type"] == "aforo_action"
    assert persisted["metadata"]["accion"] == "mover"
    assert persisted["metadata"]["punto"] == [1.25, 0, -3.5]
    assert _activity_label(persisted["event_type"], event_data["valor"], persisted) == "Acción del modelo · mover"


def test_gemelo_negative_temperature_direction_is_accepted() -> None:
    event, event_data = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "temperatura",
        "zona": "Oficina L1",
        "valor": 18.5,
        "metadata": {
            "zona_id": 1,
            "banda": "cold",
            "hvac": "calefaccion",
            "direccion": -1,
            "umbral": 28,
            "estado_actual": True,
        },
    })

    assert event.temperature_c == 18.5
    assert event_data["metadata"]["direccion"] == -1
