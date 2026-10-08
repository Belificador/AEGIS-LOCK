import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import app
from backend.routers import audit as audit_router
from backend.routers import telegram as telegram_router
from backend.core.security import create_access_token
from backend.services.argus_reporting import get_current_occupancy
from backend.services.postgres_client import postgres_service


def test_telegram_user_map_binds_numeric_ids_to_aegis_accounts() -> None:
    settings = Settings(telegram_user_map="123456:operador, 789012:admin")
    assert settings.authorized_telegram_users == {123456: "operador", 789012: "admin"}


def test_telegram_webhook_uses_allowlisted_read_only_argus_and_replies_to_sender(monkeypatch) -> None:
    calls = []
    settings = SimpleNamespace(
        telegram_webhook_secret="s" * 40,
        authorized_telegram_users={123456789: "admin"},
    )

    class FakePool:
        async def fetchval(self, _query, update_id):
            assert update_id == 301
            return update_id

        async def close(self):
            return None

    async def ask_argus(message, claims):
        calls.append((message, claims))
        return "Temperatura: 22.0 °C"

    async def get_user(username):
        assert username == "admin"
        return {"username": "admin", "role": "admin"}

    async def send_message(text, *, chat_id=None):
        calls.append((text, chat_id))

    monkeypatch.setattr(telegram_router, "get_settings", lambda: settings)
    monkeypatch.setattr(postgres_service, "pool", FakePool())
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(telegram_router, "ask_argus", ask_argus)
    monkeypatch.setattr(telegram_router, "send_telegram_message", send_message)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "s" * 40},
            json={
                "update_id": 301,
                "message": {
                    "from": {"id": 123456789, "is_bot": False},
                    "chat": {"id": 123456789, "type": "private"},
                    "text": "temperatura",
                },
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls[0] == (
        "Consulta la temperatura más reciente del edificio. Indica si no hay lectura disponible.",
        {"sub": "admin", "username": "admin", "role": "admin", "channel": "telegram"},
    )
    assert calls[1] == ("Temperatura: 22.0 °C", 123456789)


def test_telegram_webhook_rejects_wrong_webhook_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_router,
        "get_settings",
        lambda: SimpleNamespace(telegram_webhook_secret="s" * 40, authorized_telegram_users={}),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
        )
    assert response.status_code == 403


def test_evacuation_occupancy_requires_fresh_readings() -> None:
    class FakePool:
        def __init__(self, rows):
            self.rows = rows

        async def fetch(self, *_args):
            return self.rows

    now = datetime.now(timezone.utc)
    fresh = FakePool([
        {"zone": "Recepción", "occupancy": "3", "updated_at": now - timedelta(seconds=20)},
        {"zone": "Oficina L1", "occupancy": "4", "updated_at": now - timedelta(seconds=40)},
    ])
    stale = FakePool([
        {"zone": "Recepción", "occupancy": "3", "updated_at": now - timedelta(minutes=8)},
    ])

    current = asyncio.run(get_current_occupancy(pool=fresh))
    old = asyncio.run(get_current_occupancy(pool=stale))

    assert current["total"] == 7
    assert current["stale"] is False
    assert old["total"] is None
    assert old["stale"] is True


def test_confirmed_lockdown_audit_schedules_telegram_notification(monkeypatch) -> None:
    audit_entries = []
    notifications = []

    async def no_close():
        return None

    async def get_user(username):
        return {"username": username, "role": "admin", "password_hash": "unused"}

    async def write_audit_log(**values):
        audit_entries.append(values)
        return 77

    async def notify_mode(action, **details):
        notifications.append((action, details))

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(postgres_service, "write_audit_log", write_audit_log)
    monkeypatch.setattr(audit_router, "notify_mode_transition", notify_mode)
    admin_token, _ = create_access_token(subject="admin", role="admin")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/audit",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "LOCKDOWN_ACTIVATED", "details": {"source": "ACTIVACIÓN MANUAL"}},
        )

    assert response.status_code == 200
    assert audit_entries[0]["action"] == "LOCKDOWN_ACTIVATED"
    assert len(notifications) == 1
    action, details = notifications[0]
    assert action == "LOCKDOWN_ACTIVATED"
    assert details["actor"] == "admin"
    assert details["source"] == "ACTIVACIÓN MANUAL"
    assert details["event_id"] == 77
