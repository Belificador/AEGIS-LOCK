import asyncio

from backend.config import Settings
from backend.services import argus_notifications
from backend.services.postgres_client import postgres_service


def test_power_loss_notice_is_sent_once_to_admin_recipients_only(monkeypatch) -> None:
    sent = []
    users = {
        "operador": {"username": "operador", "role": "operator"},
        "admin": {"username": "admin", "role": "admin"},
    }

    async def get_user(username):
        return users.get(username)

    async def send_message(text, *, chat_id=None):
        sent.append((text, chat_id))

    monkeypatch.setattr(argus_notifications, "get_settings", lambda: Settings(
        telegram_bot_token="telegram-test-token",
        telegram_user_map="111111:operador,222222:admin",
    ))
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(argus_notifications, "send_telegram_message", send_message)

    asyncio.run(argus_notifications.notify_power_loss_transition(
        transition="loss",
        source_id="simulador",
        zone="Recepción",
        voltage=0,
        timestamp="2026-10-09T12:00:00Z",
    ))

    assert len(sent) == 1
    assert sent[0][1] == 222222
    assert "PÉRDIDA DE ALIMENTACIÓN" in sent[0][0]
    assert "Recepción" in sent[0][0]


def test_power_loss_transition_deduplicates_zero_and_detects_recovery() -> None:
    classify = argus_notifications.classify_power_loss_transition
    assert classify(None, 0) == "loss"
    assert classify(220, 0) == "loss"
    assert classify(0, 0) is None
    assert classify(0, 220) == "restored"
    assert classify(220, 220) is None
    assert classify(None, None) is None


def test_previous_voltage_is_read_from_current_persisted_state(monkeypatch) -> None:
    class FakePool:
        async def fetchval(self, query, source_id, zone):
            assert "latest_telemetry" in query
            assert source_id == "simulador"
            assert zone == "Recepción"
            return "0"

    monkeypatch.setattr(postgres_service, "pool", FakePool())
    previous = asyncio.run(postgres_service.latest_voltage_state("simulador", "Recepción"))
    assert previous == 0


def test_hermes_recovery_message_reports_returned_voltage(monkeypatch) -> None:
    sent = []

    async def get_user(username):
        return {"username": username, "role": "admin"}

    async def send_message(text, *, chat_id=None):
        sent.append((text, chat_id))

    monkeypatch.setattr(argus_notifications, "get_settings", lambda: Settings(
        telegram_bot_token="telegram-test-token",
        telegram_user_map="222222:admin",
    ))
    monkeypatch.setattr(postgres_service, "get_user", get_user)
    monkeypatch.setattr(argus_notifications, "send_telegram_message", send_message)

    asyncio.run(argus_notifications.notify_power_loss_transition(
        transition="restored",
        source_id="simulador",
        zone="Oficina L1",
        voltage=220,
        timestamp="2026-10-09T12:01:00Z",
    ))

    assert len(sent) == 1
    assert sent[0][1] == 222222
    assert "ALIMENTACIÓN RESTABLECIDA" in sent[0][0]
    assert "220 V" in sent[0][0]
