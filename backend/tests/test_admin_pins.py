from datetime import datetime, timezone

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

    async def create_pin_if_available(**values):
        created.append(values)
        stored = {
            "id": values["pin_id"],
            "door_name": values["door_name"],
            "pin_code": values["pin_code"],
            "target_user": values["target_user"],
            "created_by": values["created_by"],
            "expires_at": values["expires_at"],
            "is_active": True,
        }
        audits.append({
            "action": "PIN_GENERATED",
            "performed_by": values["created_by"],
            "details": {
                "pin_id": stored["id"],
                "door_name": stored["door_name"],
                "target_user": stored["target_user"],
            },
        })
        return stored

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "create_temporary_pin_if_hash_available", create_pin_if_available)
    admin_token, _ = create_access_token(subject="admin", role="admin")
    requested_at = datetime.now(timezone.utc)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pins/generate",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"door_name": "Puerta Lobby", "duration_hours": 48, "target_user": "visitante-17"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["door_name"] == "Puerta Lobby"
    assert len(result["pin_code"]) == 4
    assert created[0]["created_by"] == "admin"
    assert 47 * 3600 < (created[0]["expires_at"] - requested_at).total_seconds() < 49 * 3600
    assert audits[0]["action"] == "PIN_GENERATED"
    assert audits[0]["performed_by"] == "admin"
    assert "pin_code" not in audits[0]["details"]


def test_admin_can_revoke_temporary_pin_and_action_is_audited(monkeypatch) -> None:
    audits = []

    async def no_close():
        return None

    async def deactivate_and_audit(pin_id, *, performed_by):
        assert pin_id == "00000000-0000-0000-0000-000000000042"
        revoked = {
            "id": pin_id,
            "door_name": "Puerta Lobby",
            "target_user": "visitante-17",
            "created_by": "admin",
            "expires_at": datetime.now(timezone.utc),
            "is_active": False,
        }
        audits.append({
            "action": "PIN_REVOKED",
            "performed_by": performed_by,
            "details": {"pin_id": pin_id, "door_name": revoked["door_name"]},
        })
        return revoked

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "deactivate_temporary_pin_and_audit", deactivate_and_audit)
    admin_token, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        response = client.delete(
            "/api/v1/pins/00000000-0000-0000-0000-000000000042",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": "00000000-0000-0000-0000-000000000042", "is_active": False}
    assert audits[0]["action"] == "PIN_REVOKED"
    assert audits[0]["performed_by"] == "admin"


def test_operator_cannot_generate_temporary_pins() -> None:
    operator_token, _ = create_access_token(subject="operador", role="operator")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pins/generate",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={"door_name": "Puerta Lobby", "duration_hours": 8, "target_user": "visitante-17"},
        )
        listing = client.get("/api/v1/pins", headers={"Authorization": f"Bearer {operator_token}"})
        revocation = client.delete(
            "/api/v1/pins/00000000-0000-0000-0000-000000000042",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
    assert response.status_code == 403
    assert listing.status_code == 403
    assert revocation.status_code == 403


def test_admin_pin_revocation_rejects_malformed_uuid_before_database_access(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def fail_if_called(_pin_id):
        raise AssertionError("Malformed UUID must be rejected before database access")

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "deactivate_temporary_pin_and_audit", fail_if_called)
    admin_token, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        response = client.delete(
            "/api/v1/pins/not-a-uuid",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 422


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
