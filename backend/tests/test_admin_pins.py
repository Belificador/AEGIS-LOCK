from fastapi.testclient import TestClient

from backend.config import Settings
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import pins
from backend.services.postgres_client import postgres_service


def test_admin_can_generate_temporary_pin_and_actor_comes_from_jwt(monkeypatch) -> None:
    audits = []
    created = []

    async def no_close():
        return None

    async def hash_exists(_door, _pin_hash):
        return False

    async def create_pin(**values):
        created.append(values)
        return {
            "id": values["pin_id"],
            "door_name": values["door_name"],
            "pin_code": values["pin_code"],
            "target_user": values["target_user"],
            "created_by": values["created_by"],
            "expires_at": values["expires_at"],
            "is_active": True,
        }

    async def write_audit_log(**values):
        audits.append(values)
        return 1

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "temporary_pin_hash_exists", hash_exists)
    monkeypatch.setattr(postgres_service, "create_temporary_pin", create_pin)
    monkeypatch.setattr(postgres_service, "write_audit_log", write_audit_log)
    admin_token, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pins/generate",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"door_name": "Puerta Lobby", "duration_hours": 8, "target_user": "visitante-17"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["door_name"] == "Puerta Lobby"
    assert len(result["pin_code"]) == 4
    assert created[0]["created_by"] == "admin"
    assert audits[0]["action"] == "PIN_GENERATED"
    assert audits[0]["performed_by"] == "admin"
    assert "pin_code" not in audits[0]["details"]


def test_operator_cannot_generate_temporary_pins() -> None:
    operator_token, _ = create_access_token(subject="operador", role="operator")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pins/generate",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={"door_name": "Puerta Lobby", "duration_hours": 8, "target_user": "visitante-17"},
        )
    assert response.status_code == 403


def test_gemelo_service_can_validate_a_render_pin_without_exposing_it(monkeypatch) -> None:
    checks = []
    audits = []

    async def validate_pin(door_name, pin_hash):
        checks.append((door_name, pin_hash))
        return {"id": "pin-id", "door_name": door_name, "target_user": "visitante-17"}

    async def write_audit_log(**values):
        audits.append(values)

    async def no_close():
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "validate_temporary_pin", validate_pin)
    monkeypatch.setattr(postgres_service, "write_audit_log", write_audit_log)
    monkeypatch.setattr(pins, "get_settings", lambda: Settings(telemetry_api_key="server-to-server-test-key"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pins/validate",
            headers={"Authorization": "Bearer server-to-server-test-key"},
            json={"door_name": "Recepción", "pin_code": "0042"},
        )

    assert response.status_code == 200
    assert response.json() == {"valid": True, "target_user": "visitante-17", "pin_id": "pin-id"}
    assert checks[0][0] == "Puerta Lobby"
    assert "0042" not in checks[0][1]
    assert audits[0]["action"] == "PIN_VALIDATED"
    assert "pin_code" not in audits[0]["details"]
