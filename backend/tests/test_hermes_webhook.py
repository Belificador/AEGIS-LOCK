from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.config import Settings
from backend.main import app
from backend.routers import telegram as hermes
from backend.services.postgres_client import postgres_service


def test_telegram_user_map_is_normalized_and_rejects_duplicate_accounts() -> None:
    settings = Settings(telegram_user_map="123456789:Operador,987654321:admin")
    assert settings.authorized_telegram_users == {123456789: "operador", 987654321: "admin"}
    with pytest.raises(ValidationError):
        Settings(telegram_user_map="123456789:admin,987654321:admin")


def test_argus_cron_settings_need_only_report_credentials() -> None:
    settings = Settings(
        environment="production",
        service_role="argus_cron",
        argus_report_database_url="postgresql://readonly:password@db.example.test/aegis",
        openrouter_api_key="provider-test-key",
        telegram_bot_token="telegram-test-token",
        telegram_chat_id="123456789",
    )
    assert settings.service_role == "argus_cron"


def test_hermes_accepts_authorized_private_chat_and_calls_argus_read_only(monkeypatch) -> None:
    calls = []

    class FakePool:
        async def fetchval(self, _query, update_id):
            return update_id

    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def get_user(username):
        assert username == "operador"
        return {"username": "operador", "role": "operator"}

    async def ask_argus(message, claims):
        calls.append((message, claims))
        return "Temperatura: 22 °C"

    async def send_message(text, *, chat_id=None):
        calls.append((text, chat_id))

    monkeypatch.setattr(hermes, "get_settings", lambda: Settings(
        telegram_webhook_secret="s" * 40,
        telegram_user_map="123456789:operador",
    ))
    monkeypatch.setattr(hermes, "ask_argus", ask_argus)
    monkeypatch.setattr(hermes, "send_telegram_message", send_message)
    monkeypatch.setattr(postgres_service, "pool", FakePool())
    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "get_user", get_user)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "s" * 40},
            json={
                "update_id": 83001,
                "message": {
                    "from": {"id": 123456789, "is_bot": False},
                    "chat": {"id": 123456789, "type": "private"},
                    "text": "/temperatura",
                },
            },
        )

    assert response.status_code == 200
    assert calls[0] == (
        "Consulta la temperatura más reciente del edificio. Indica si no hay lectura disponible.",
        {"sub": "operador", "username": "operador", "role": "operator", "channel": "telegram"},
    )
    assert calls[1] == ("Temperatura: 22 °C", 123456789)


def test_hermes_rejects_invalid_webhook_secret(monkeypatch) -> None:
    monkeypatch.setattr(hermes, "get_settings", lambda: Settings(telegram_webhook_secret="s" * 40))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
        )
    assert response.status_code == 403


def test_hermes_ignores_group_messages(monkeypatch) -> None:
    replies = []

    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    async def send_message(text, *, chat_id=None):
        replies.append((text, chat_id))

    monkeypatch.setattr(hermes, "get_settings", lambda: Settings(
        telegram_webhook_secret="s" * 40,
        telegram_user_map="123456789:operador",
    ))
    monkeypatch.setattr(hermes, "send_telegram_message", send_message)
    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "s" * 40},
            json={
                "update_id": 83002,
                "message": {
                    "from": {"id": 123456789, "is_bot": False},
                    "chat": {"id": -100123456, "type": "group"},
                    "text": "estado",
                },
            },
        )

    assert response.status_code == 200
    assert replies == []
