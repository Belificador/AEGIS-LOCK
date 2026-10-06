from fastapi.testclient import TestClient

from backend.core.passwords import hash_password
from backend.core.security import decode_access_token
from backend.main import app
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

    async def no_close():
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(postgres_service, "issue_refresh_token", issue_refresh_token)
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
