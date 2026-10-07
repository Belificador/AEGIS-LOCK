import asyncio

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.core.passwords import hash_password
from backend.core.security import decode_access_token
from backend.main import app, health
from backend.services.postgres_client import postgres_service


def test_demo_login_issues_role_bearing_jwt_from_postgres_user(monkeypatch) -> None:
    async def get_user(username: str):
        if username == "operador":
            return {
                "username": "operador",
                "password_hash": hash_password("demo-password-123"),
                "role": "operator",
            }
        return None

    async def issue_refresh_token(username: str, *, days: int):
        assert username == "operador"
        assert days == 7
        return "opaque-refresh-token-for-tests"

    async def write_audit_log(**_values):
        return 1

    async def no_close():
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(postgres_service, "issue_refresh_token", issue_refresh_token)
    monkeypatch.setattr(postgres_service, "write_audit_log", write_audit_log)
    monkeypatch.setattr(postgres_service, "close", no_close)

    with TestClient(app) as client:
        response = client.post(
            "/api/login",
            json={"username": "Operador", "password": "demo-password-123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": "operador", "username": "operador", "role": "operator"}
    assert body["refresh_token"] == "opaque-refresh-token-for-tests"
    assert decode_access_token(body["access_token"])["role"] == "operator"


def test_local_health_distinguishes_missing_database(monkeypatch) -> None:
    from backend import main

    async def unhealthy():
        return False

    monkeypatch.setattr(postgres_service, "is_healthy", unhealthy)
    monkeypatch.setattr(main, "settings", Settings(environment="local"))
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/health", "headers": [], "client": ("127.0.0.1", 1234)})
    response = asyncio.run(health(request))
    assert response.status_code == 200
    assert response.body == b'{"status":"ok","service":"aegis-lock-api","database":"not_configured"}'


def test_logout_revokes_refresh_token_without_exposing_it(monkeypatch) -> None:
    revoked = []
    audits = []

    async def no_close():
        return None

    async def revoke(token):
        revoked.append(token)
        return "operador"

    async def audit(**values):
        audits.append(values)
        return 1

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "revoke_refresh_token", revoke)
    monkeypatch.setattr(postgres_service, "write_audit_log", audit)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/logout", json={"refresh_token": "opaque-refresh-token-for-tests"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert revoked == ["opaque-refresh-token-for-tests"]
    assert audits[0]["action"] == "LOGOUT"
    assert audits[0]["performed_by"] == "operador"
