from fastapi.testclient import TestClient

from backend.core.security import create_access_token
from backend.main import app
from backend.services.postgres_client import postgres_service


def test_viewer_is_read_only_but_can_read_the_shared_building_camera_catalog(monkeypatch) -> None:
    async def no_close():
        return None

    async def get_user(username):
        return {"username": username, "role": "viewer", "password_hash": "unused"}

    async def no_error_log(**_values):
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(postgres_service, "write_error_log", no_error_log)
    viewer_token, _ = create_access_token(subject="viewer-1", role="viewer")
    headers = {"Authorization": f"Bearer {viewer_token}"}

    with TestClient(app) as client:
        catalog = client.get("/api/v1/cameras", headers=headers)
        analytics = client.get("/api/v1/analytics/history", headers=headers)
        pins = client.get("/api/v1/pins/doors", headers=headers)
        audit = client.post(
            "/api/v1/audit",
            headers=headers,
            json={"action": "LOCKDOWN_ACTIVATED", "details": {"source": "test"}},
        )

    assert catalog.status_code == 200
    assert len(catalog.json()) == 9
    assert analytics.status_code == 403
    assert pins.status_code == 403
    assert audit.status_code == 403
