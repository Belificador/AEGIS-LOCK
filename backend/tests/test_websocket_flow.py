from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from backend.config import Settings
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import telemetry, ws_manager
from backend.services.postgres_client import postgres_service


def test_server_relay_ingests_validates_alerts_and_broadcasts(monkeypatch) -> None:
    dashboard_token, _ = create_access_token(subject="viewer-1", role="viewer")
    events = []

    async def persist_event(event, alerts):
        events.append((event, alerts))

    async def no_latest_events():
        return []

    async def no_close():
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "persist_event", persist_event)
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(telemetry, "get_settings", lambda: Settings(telemetry_api_key="test-server-secret"))

    raw_payload = (
        '{ "origen": "simulador", "tipo_evento": "temperatura", "zona": "entrada", '
        '"valor": 39, "timestamp": "2026-10-05T12:00:00Z", "metadata": {"sensor": "real-01"} }'
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/dashboard", headers={"origin": "http://localhost:5500"}
        ) as dashboard:
            dashboard.send_json({"type": "auth", "token": dashboard_token})
            assert dashboard.receive_json() == {"kind": "connection", "status": "authenticated"}

            with client.websocket_connect(
                "/ws/dashboard", headers={"origin": "http://localhost:5500"}
            ) as second_dashboard:
                second_dashboard.send_json({"type": "auth", "token": dashboard_token})
                assert second_dashboard.receive_json() == {"kind": "connection", "status": "authenticated"}

                with client.websocket_connect(
                    "/ws/telemetry", headers={"authorization": "Bearer test-server-secret"}
                ) as telemetry_socket:
                    assert telemetry_socket.receive_json() == {
                        "kind": "connection",
                        "status": "authenticated",
                    }
                    telemetry_socket.send_text(raw_payload)
                    broadcast = dashboard.receive_json()
                    second_broadcast = second_dashboard.receive_json()
                    acknowledgement = telemetry_socket.receive_json()

        assert broadcast["kind"] == "telemetry"
        assert second_broadcast == broadcast
        assert broadcast["event"]["source_id"] == "simulador"
        assert broadcast["event"]["temperature_c"] == 39
        assert broadcast["alerts"][0]["code"] == "HIGH_TEMPERATURE"
        assert acknowledgement["kind"] == "ack"
        assert acknowledgement["persisted"] is True
        assert events[0][0]["tipo_evento"] == "temperatura"


def test_dashboard_websocket_echoes_heartbeat_round_trip() -> None:
    token, _ = create_access_token(subject="operator-1", role="operator")
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/dashboard", headers={"origin": "http://localhost:5500"}
        ) as dashboard:
            dashboard.send_json({"type": "auth", "token": token})
            assert dashboard.receive_json() == {"kind": "connection", "status": "authenticated"}
            dashboard.send_json({"type": "ping", "id": "ping-test-1"})
            pong = dashboard.receive_json()
            assert pong["kind"] == "heartbeat"
            assert pong["type"] == "pong"
            assert pong["id"] == "ping-test-1"
            assert isinstance(pong["server_time"], int)


def test_operator_can_read_dashboard_but_cannot_publish_telemetry() -> None:
    token, _ = create_access_token(subject="operador", role="operator")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as telemetry_socket:
            telemetry_socket.send_json({"type": "auth", "token": token})
            with pytest.raises(WebSocketDisconnect) as disconnected:
                telemetry_socket.receive_json()

    assert disconnected.value.code == 4403


def test_dashboard_websocket_rejects_untrusted_origin(monkeypatch) -> None:
    async def no_error_log(**_values):
        return None

    monkeypatch.setattr(ws_manager, "get_settings", lambda: Settings(allowed_origins=["http://localhost:5500"]))
    monkeypatch.setattr(postgres_service, "write_error_log", no_error_log)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnected:
            with client.websocket_connect("/ws/dashboard", headers={"origin": "https://attacker.example"}):
                pass

    assert disconnected.value.code == 4403


def test_websocket_rejects_malformed_and_oversized_frames_then_remains_usable(monkeypatch) -> None:
    persisted_events = []

    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def no_latest_events():
        return []

    async def persist_event(event, alerts):
        persisted_events.append((event, alerts))

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "persist_event", persist_event)
    monkeypatch.setattr(
        telemetry,
        "get_settings",
        lambda: Settings(telemetry_api_key="test-server-secret", max_request_bytes=1024),
    )

    valid_payload = (
        '{"origen":"simulador","tipo_evento":"temperatura","zona":"entrada","valor":22}'
    )
    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/telemetry", headers={"authorization": "Bearer test-server-secret"}
        ) as telemetry_socket:
            assert telemetry_socket.receive_json() == {"kind": "connection", "status": "authenticated"}
            telemetry_socket.send_text("x" * 1025)
            too_large = telemetry_socket.receive_json()
            telemetry_socket.send_text("{")
            malformed = telemetry_socket.receive_json()
            telemetry_socket.send_text(valid_payload)
            acknowledgement = telemetry_socket.receive_json()

    assert too_large == {"kind": "error", "detail": "Evento demasiado grande"}
    assert malformed == {"kind": "error", "detail": "Evento de telemetría inválido"}
    assert acknowledgement["kind"] == "ack"
    assert acknowledgement["persisted"] is True
    assert len(persisted_events) == 1
    assert persisted_events[0][0]["temperature_c"] == 22


def test_telemetry_ack_does_not_claim_persistence_when_database_fails(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def no_latest_events():
        return []

    async def fail_persist(_event, _alerts):
        raise RuntimeError("simulated database outage")

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "persist_event", fail_persist)
    monkeypatch.setattr(telemetry, "get_settings", lambda: Settings(telemetry_api_key="test-server-secret"))

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/telemetry", headers={"authorization": "Bearer test-server-secret"}
        ) as telemetry_socket:
            assert telemetry_socket.receive_json() == {"kind": "connection", "status": "authenticated"}
            telemetry_socket.send_json({
                "origen": "simulador",
                "tipo_evento": "temperatura",
                "zona": "entrada",
                "valor": 22,
            })
            acknowledgement = telemetry_socket.receive_json()

    assert acknowledgement["kind"] == "ack"
    assert acknowledgement["persisted"] is False


def test_entry_during_lockdown_is_alerted_and_sent_to_hermes(monkeypatch) -> None:
    persisted_events = []
    scheduled = []

    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def no_latest_events():
        return []

    async def persist_event(event, alerts):
        persisted_events.append((event, alerts))

    async def no_audit(**_values):
        return 1

    async def lockdown_state():
        return {"mode": "LOCKDOWN", "action": "LOCKDOWN_ACTIVATED"}

    def schedule_notices(event, alerts):
        scheduled.append((event, alerts))

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "persist_event", persist_event)
    monkeypatch.setattr(postgres_service, "write_audit_log", no_audit)
    monkeypatch.setattr(postgres_service, "current_security_mode", lockdown_state)
    monkeypatch.setattr(telemetry, "schedule_telemetry_notices", schedule_notices)
    monkeypatch.setattr(telemetry, "get_settings", lambda: Settings(telemetry_api_key="test-server-secret"))

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/telemetry", headers={"authorization": "Bearer test-server-secret"}
        ) as telemetry_socket:
            assert telemetry_socket.receive_json() == {"kind": "connection", "status": "authenticated"}
            telemetry_socket.send_json({
                "origen": "simulador",
                "tipo_evento": "acceso_pin",
                "zona": "Puerta Lobby",
                "valor": "GRANTED",
                "metadata": {"access_direction": "ENTRY"},
            })
            acknowledgement = telemetry_socket.receive_json()

    lockdown_alerts = [alert for alert in acknowledgement["alerts"] if alert["code"] == "ENTRY_DURING_LOCKDOWN"]
    assert acknowledgement["persisted"] is True
    assert len(lockdown_alerts) == 1
    assert lockdown_alerts[0]["message"].startswith("Acaba de ingresar una persona con el Lockdown activo")
    assert len(persisted_events) == 1
    assert scheduled[0][1] == acknowledgement["alerts"]
