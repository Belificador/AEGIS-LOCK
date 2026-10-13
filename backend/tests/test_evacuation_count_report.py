import asyncio
from datetime import datetime, timedelta, timezone

from backend.config import Settings
from backend.jobs import evacuation_count_report as evacuation_job


class FakeReportPool:
    def __init__(self, *, mode_row, occupancy_rows=(), admin_rows=()):
        self.mode_row = mode_row
        self.occupancy_rows = list(occupancy_rows)
        self.admin_rows = list(admin_rows)
        self.closed = False

    async def fetchrow(self, _query, _actions):
        return self.mode_row

    async def fetch(self, query, *_args):
        if "FROM latest_telemetry" in query:
            return self.occupancy_rows
        if "FROM aegis_users" in query:
            return self.admin_rows
        raise AssertionError("Unexpected report query")

    async def close(self):
        self.closed = True


def test_current_occupancy_preserves_zero_and_requires_fresh_expected_zones() -> None:
    now = datetime.now(timezone.utc)
    pool = FakeReportPool(
        mode_row=None,
        occupancy_rows=[
            {"zone": "Recepción", "occupancy": 0, "updated_at": now},
            {"zone": "Oficina L1", "occupancy": 5, "updated_at": now},
        ],
    )

    result = asyncio.run(evacuation_job.current_occupancy(
        pool, ("Recepción", "Oficina L1"), stale_after_seconds=180
    ))

    assert result["total"] == 5
    assert result["complete"] is True
    assert result["unavailable"] == []
    assert result["fresh"][0]["occupancy"] == 0


def test_current_occupancy_marks_missing_and_stale_zones_partial() -> None:
    now = datetime.now(timezone.utc)
    pool = FakeReportPool(
        mode_row=None,
        occupancy_rows=[
            {"zone": "Recepción", "occupancy": 3, "updated_at": now},
            {"zone": "Oficina L1", "occupancy": 4, "updated_at": now - timedelta(seconds=400)},
        ],
    )

    result = asyncio.run(evacuation_job.current_occupancy(
        pool, ("Recepción", "Oficina L1", "Gerencia"), stale_after_seconds=180
    ))

    assert result["total"] == 3
    assert result["complete"] is False
    assert set(result["unavailable"]) == {"Oficina L1", "Gerencia"}


def test_evacuation_cron_sends_count_only_to_mapped_active_admins(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    pool = FakeReportPool(
        mode_row={
            "id": 12,
            "action": "EVACUATION_ACTIVATED",
            "performed_by": "admin",
            "timestamp": now,
        },
        occupancy_rows=[
            {"zone": "Recepción", "occupancy": 0, "updated_at": now},
            {"zone": "Oficina L1", "occupancy": 5, "updated_at": now},
        ],
        admin_rows=[{"username": "admin"}],
    )
    sent = []
    settings = Settings(
        service_role="evacuation_cron",
        argus_report_database_url="postgresql://readonly:password@db.example.test/aegis",
        telegram_bot_token="test-bot-token",
        telegram_user_map="111111:admin,222222:operador",
        evacuation_expected_zones="Recepción,Oficina L1",
    )

    async def create_pool(**_kwargs):
        return pool

    async def send_message(text, *, chat_id=None):
        sent.append((text, chat_id))

    monkeypatch.setattr(evacuation_job, "get_settings", lambda: settings)
    monkeypatch.setattr(evacuation_job.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(evacuation_job, "send_telegram_message", send_message)

    asyncio.run(evacuation_job.run_evacuation_count_report())

    assert pool.closed is True
    assert len(sent) == 1
    assert sent[0][1] == "111111"
    assert "Personas por evacuar: 5" in sent[0][0]
    assert "EVACUACIÓN SIMULADA ACTIVA" in sent[0][0]


def test_evacuation_cron_sends_nothing_after_mode_release(monkeypatch) -> None:
    pool = FakeReportPool(
        mode_row={
            "id": 13,
            "action": "EVACUATION_RELEASED",
            "performed_by": "admin",
            "timestamp": datetime.now(timezone.utc),
        },
    )
    sent = []
    settings = Settings(
        service_role="evacuation_cron",
        argus_report_database_url="postgresql://readonly:password@db.example.test/aegis",
        telegram_bot_token="test-bot-token",
        telegram_user_map="111111:admin",
    )

    async def create_pool(**_kwargs):
        return pool

    async def send_message(text, *, chat_id=None):
        sent.append((text, chat_id))

    monkeypatch.setattr(evacuation_job, "get_settings", lambda: settings)
    monkeypatch.setattr(evacuation_job.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(evacuation_job, "send_telegram_message", send_message)

    asyncio.run(evacuation_job.run_evacuation_count_report())

    assert pool.closed is True
    assert sent == []
