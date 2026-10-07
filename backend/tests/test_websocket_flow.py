from fastapi.testclient import TestClient

from backend.config import Settings
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import telemetry
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

    async def get_user(username):
        if username == "viewer-1":
            return {"username": username, "role": "viewer", "password_hash": "unused"}
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "persist_event", persist_event)
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
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
                "/ws/telemetry", headers={"authorization": "Bearer test-server-secret"}
            ) as telemetry_socket:
                assert telemetry_socket.receive_json() == {
                    "kind": "connection",
                    "status": "authenticated",
                }
                telemetry_socket.send_text(raw_payload)
                broadcast = dashboard.receive_json()
                acknowledgement = telemetry_socket.receive_json()

        assert broadcast["kind"] == "telemetry"
        assert broadcast["event"]["source_id"] == "simulador"
        assert broadcast["event"]["temperature_c"] == 39
        assert broadcast["alerts"][0]["code"] == "HIGH_TEMPERATURE"
        assert acknowledgement["kind"] == "ack"
        assert acknowledgement["persisted"] is True
        assert events[0][0]["tipo_evento"] == "temperatura"


def test_dashboard_websocket_echoes_heartbeat_round_trip(monkeypatch) -> None:
    async def no_close():
        return None

    async def no_latest_events():
        return []

    async def get_user(username):
        return {"username": username, "role": "operator", "password_hash": "unused"}

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
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
