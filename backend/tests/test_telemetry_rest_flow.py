from fastapi.testclient import TestClient

from backend.config import Settings
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import telemetry_rest, ws_manager
from backend.services.postgres_client import postgres_service


def test_rest_ingest_and_dashboard_poll_preserve_zero_aforo_and_illumination(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def no_latest_events():
        return []

    async def enqueue(_event, _alerts):
        return True

    async def get_user(username):
        role = {"admin": "admin", "viewer": "viewer"}.get(username)
        return {"username": username, "role": role} if role else None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "latest_events", no_latest_events)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(ws_manager.manager, "start", no_connect)
    monkeypatch.setattr(ws_manager.manager, "enqueue_persistence", enqueue)
    monkeypatch.setattr(telemetry_rest, "get_settings", lambda: Settings(telemetry_api_key="test-server-secret"))
    monkeypatch.setattr(ws_manager.manager, "_local_states", {})
    admin, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        occupancy = client.post(
            "/api/v1/telemetry",
            headers={"Authorization": "Bearer test-server-secret"},
            json={
                "origen": "simulador",
                "tipo_evento": "aforo",
                "zona": "Todas",
                "valor": 0,
                "metadata": {"alcance": "global", "estado_actual": True},
            },
        )
        lighting = client.post(
            "/api/v1/telemetry",
            headers={"Authorization": "Bearer test-server-secret"},
            json={
                "origen": "simulador",
                "tipo_evento": "iluminacion",
                "zona": "Administración",
                "valor": 0,
                "metadata": {"zona_id": 3, "unidad": "%", "factor_electrico": 0, "estado_actual": True},
            },
        )
        snapshot = client.get("/api/v1/telemetry/latest", headers={"Authorization": f"Bearer {admin}"})

    assert occupancy.status_code == 202
    assert occupancy.json()["accepted"] is True
    assert occupancy.json()["queued_for_persistence"] is True
    assert lighting.status_code == 202
    assert snapshot.status_code == 200
    events = {item["event"]["tipo_evento"]: item["event"] for item in snapshot.json()["events"]}
    assert events["aforo"]["occupancy"] == 0
    assert events["iluminacion"]["valor"] == 0
    assert events["iluminacion"]["metadata"]["zona_id"] == 3


def test_rest_ingest_rejects_missing_service_key_and_viewer_writes(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def get_user(username):
        role = {"viewer": "viewer"}.get(username)
        return {"username": username, "role": role} if role else None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(ws_manager.manager, "start", no_connect)
    monkeypatch.setattr(telemetry_rest, "get_settings", lambda: Settings(telemetry_api_key="test-server-secret"))
    viewer, _ = create_access_token(subject="viewer", role="viewer")
    event = {"origen": "simulador", "tipo_evento": "aforo", "zona": "Todas", "valor": 0}

    with TestClient(app) as client:
        missing = client.post("/api/v1/telemetry", json=event)
        viewer_write = client.post(
            "/api/v1/telemetry",
            headers={"Authorization": f"Bearer {viewer}"},
            json=event,
        )

    assert missing.status_code == 401
    assert viewer_write.status_code == 403
