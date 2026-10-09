from fastapi.testclient import TestClient

from backend.agents.argus.client import OpenRouterError
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import ai_chat
from backend.services.postgres_client import postgres_service


def test_argus_chat_requires_authenticated_dashboard_session(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def ask_argus(message, claims):
        assert message == "Consulta el estado"
        assert claims["role"] == "operator"
        return "Estado consultado por Argus."

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(ai_chat, "ask_argus", ask_argus)
    token, _ = create_access_token(subject="operador", role="operator")

    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/chat", json={"message": "Consulta el estado"})
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Consulta el estado"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {"response": "Estado consultado por Argus.", "source": "openrouter-argus"}


def test_argus_chat_returns_safe_provider_configuration_error(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def ask_argus(*_args, **_kwargs):
        raise OpenRouterError("Falta OPENROUTER_API_KEY")

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(ai_chat, "ask_argus", ask_argus)
    token, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Consulta el estado"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Falta OPENROUTER_API_KEY"
