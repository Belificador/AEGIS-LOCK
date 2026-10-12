import asyncio

from backend.services import argus_notifications


def test_telemetry_power_loss_and_recovery_are_sent_once_without_database_io(monkeypatch) -> None:
    sent = []

    async def capture(message):
        sent.append(message)

    monkeypatch.setattr(argus_notifications, "_last_voltage", {})
    monkeypatch.setattr(argus_notifications, "_last_notice_at", {})
    monkeypatch.setattr(argus_notifications, "_in_flight", set())
    monkeypatch.setattr(argus_notifications, "_send_to_admins", capture)

    async def flush_notifications():
        while argus_notifications._in_flight:
            await asyncio.gather(*tuple(argus_notifications._in_flight))

    async def exercise():
        argus_notifications.seed_power_voltage_state([{
            "event": {"source_id": "simulador", "zone": "Recepción", "voltage_v": 220},
        }])
        power_loss = [{"code": "POWER_LOSS", "severity": "critical", "message": "0 V"}]
        argus_notifications.schedule_telemetry_notices(
            {"origen": "simulador", "zona": "Recepción", "voltage_v": 0}, power_loss,
        )
        await flush_notifications()
        argus_notifications.schedule_telemetry_notices(
            {"origen": "simulador", "zona": "Recepción", "voltage_v": 0}, power_loss,
        )
        await flush_notifications()
        argus_notifications.schedule_telemetry_notices(
            {"origen": "simulador", "zona": "Recepción", "voltage_v": 220}, [],
        )
        await flush_notifications()

    asyncio.run(exercise())

    assert len(sent) == 2
    assert "PÉRDIDA DE ALIMENTACIÓN" in sent[0]
    assert "ALIMENTACIÓN RESTABLECIDA" in sent[1]


def test_critical_alerts_are_cooldown_deduplicated(monkeypatch) -> None:
    sent = []

    async def capture(message):
        sent.append(message)

    monkeypatch.setattr(argus_notifications, "_last_voltage", {})
    monkeypatch.setattr(argus_notifications, "_last_notice_at", {})
    monkeypatch.setattr(argus_notifications, "_in_flight", set())
    monkeypatch.setattr(argus_notifications, "_send_to_admins", capture)

    async def exercise():
        event = {"source_id": "simulador", "zone": "Oficina L1", "timestamp": "now"}
        alerts = [{"code": "HIGH_TEMPERATURE", "severity": "critical", "message": "40 °C"}]
        argus_notifications.schedule_telemetry_notices(event, alerts)
        while argus_notifications._in_flight:
            await asyncio.gather(*tuple(argus_notifications._in_flight))
        argus_notifications.schedule_telemetry_notices(event, alerts)
        while argus_notifications._in_flight:
            await asyncio.gather(*tuple(argus_notifications._in_flight))

    asyncio.run(exercise())

    assert len(sent) == 1
    assert "40 °C" in sent[0]


def test_mode_transition_notification_is_fire_and_forget_and_deduplicated(monkeypatch) -> None:
    sent = []

    async def capture(message):
        sent.append(message)

    monkeypatch.setattr(argus_notifications, "_last_notice_at", {})
    monkeypatch.setattr(argus_notifications, "_in_flight", set())
    monkeypatch.setattr(argus_notifications, "_send_to_admins", capture)

    async def exercise():
        argus_notifications.schedule_mode_transition(
            "EVACUATION_ACTIVATED", "admin", {"source": "Dashboard"}, 10,
        )
        argus_notifications.schedule_mode_transition(
            "EVACUATION_ACTIVATED", "admin", {"source": "Dashboard"}, 10,
        )
        while argus_notifications._in_flight:
            await asyncio.gather(*tuple(argus_notifications._in_flight))

    asyncio.run(exercise())

    assert len(sent) == 1
    assert "EVACUACIÓN SIMULADA ACTIVADA" in sent[0]
