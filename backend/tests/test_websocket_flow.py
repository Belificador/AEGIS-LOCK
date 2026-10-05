from fastapi.testclient import TestClient

from backend.core.security import create_access_token
from backend.main import app


def test_authenticated_telemetry_broadcasts_to_dashboard() -> None:
    dashboard_token, _ = create_access_token(subject="viewer-1", role="viewer")
    operator_token, _ = create_access_token(subject="operator-1", role="operator")

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/dashboard", headers={"origin": "http://localhost:5500"}
        ) as dashboard:
            dashboard.send_json({"type": "auth", "token": dashboard_token})
            assert dashboard.receive_json() == {"kind": "connection", "status": "authenticated"}

            with client.websocket_connect(
                "/ws/telemetry", headers={"origin": "http://localhost:5500"}
            ) as telemetry:
                telemetry.send_json({"type": "auth", "token": operator_token})
                assert telemetry.receive_json() == {"kind": "connection", "status": "authenticated"}
                telemetry.send_json(
                    {
                        "source_id": "sensor-01",
                        "temperature_c": 39,
                        "voltage_v": 220,
                    }
                )

                acknowledgment = telemetry.receive_json()
                broadcast = dashboard.receive_json()

    assert acknowledgment["kind"] == "ack"
    assert broadcast["kind"] == "telemetry"
    assert broadcast["event"]["source_id"] == "sensor-01"
    assert broadcast["alerts"][0]["code"] == "HIGH_TEMPERATURE"
