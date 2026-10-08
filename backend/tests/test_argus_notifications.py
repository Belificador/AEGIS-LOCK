import asyncio
from types import SimpleNamespace

from backend.services import argus_notifications
from backend.services.postgres_client import postgres_service


def test_evacuation_transition_sends_fresh_count_to_allowlisted_users(monkeypatch) -> None:
    delivered = []

    async def current_occupancy():
        return {"total": 7, "updated_at": "2026-10-08T18:00:00+00:00", "stale": False}

    async def send_message(text, *, chat_id=None):
        delivered.append((text, chat_id))

    monkeypatch.setattr(
        argus_notifications,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="bot-token",
            telegram_chat_id=None,
            authorized_telegram_users={101: "operador", 202: "admin"},
        ),
    )
    monkeypatch.setattr(argus_notifications, "get_current_occupancy", current_occupancy)
    monkeypatch.setattr(argus_notifications, "send_telegram_message", send_message)

    async def active_user(username):
        return {"username": username} if username in {"operador", "admin"} else None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "get_user", active_user)

    asyncio.run(argus_notifications.notify_mode_transition(
        "EVACUATION_ACTIVATED",
        actor="admin",
        source="ACTIVACIÓN MANUAL",
        event_id=55,
    ))

    assert [item[1] for item in delivered] == ["101", "202"]
    assert all("EVACUACIÓN SIMULADA ACTIVADA" in item[0] for item in delivered)
    assert all("Personas que permanecen en el edificio: 7" in item[0] for item in delivered)


def test_authorized_entry_notification_never_includes_person_or_pin(monkeypatch) -> None:
    delivered = []

    async def send_message(text, *, chat_id=None):
        delivered.append((text, chat_id))

    monkeypatch.setattr(
        argus_notifications,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="bot-token",
            telegram_chat_id=None,
            authorized_telegram_users={101: "operador"},
        ),
    )
    monkeypatch.setattr(argus_notifications, "send_telegram_message", send_message)

    async def active_user(username):
        return {"username": username}

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "get_user", active_user)

    asyncio.run(argus_notifications.notify_access_entry({
        "tipo_evento": "acceso_pin",
        "valor": "GRANTED",
        "zona": "Puerta Lobby",
        "timestamp": "2026-10-08T18:00:00+00:00",
        "metadata": {
            "access_direction": "entry",
            "target_user": "visitante-privado",
            "pin_id": "pin-private-id",
        },
    }))

    assert len(delivered) == 1
    message, target = delivered[0]
    assert target == "101"
    assert "ENTRADA AUTORIZADA" in message
    assert "Puerta Lobby" in message
    assert "visitante-privado" not in message
    assert "pin-private-id" not in message


def test_access_without_entry_direction_does_not_claim_an_entry(monkeypatch) -> None:
    delivered = []

    async def send_message(text, *, chat_id=None):
        delivered.append((text, chat_id))

    monkeypatch.setattr(
        argus_notifications,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="bot-token",
            telegram_chat_id=None,
            authorized_telegram_users={101: "operador"},
        ),
    )
    monkeypatch.setattr(argus_notifications, "send_telegram_message", send_message)

    asyncio.run(argus_notifications.notify_access_entry({"tipo_evento": "acceso_pin", "valor": "GRANTED", "metadata": {}}))

    assert delivered == []
