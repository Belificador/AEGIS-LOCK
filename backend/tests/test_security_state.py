import asyncio
from datetime import datetime, timezone

from backend.services.security_state import read_current_security_mode


class ModeRow:
    def __init__(self, **values):
        self.values = values

    def __getitem__(self, key):
        return self.values[key]


class FakeModePool:
    def __init__(self, row):
        self.row = row
        self.query = ""

    async def fetchrow(self, query, actions):
        self.query = query
        assert {"LOCKDOWN_ACTIVATED", "LOCKDOWN_RELEASED", "EVACUATION_ACTIVATED", "EVACUATION_RELEASED"} == set(actions)
        return self.row


def test_security_state_comes_from_last_durable_transition() -> None:
    updated_at = datetime.now(timezone.utc)
    pool = FakeModePool(ModeRow(
        id=17,
        action="LOCKDOWN_ACTIVATED",
        performed_by="admin",
        timestamp=updated_at,
    ))

    state = asyncio.run(read_current_security_mode(pool))

    assert state == {
        "mode": "LOCKDOWN",
        "action": "LOCKDOWN_ACTIVATED",
        "transition_id": 17,
        "updated_at": updated_at,
        "updated_by": "admin",
    }
    assert "ORDER BY id DESC" in pool.query


def test_security_state_is_unknown_without_database_not_assumed_normal() -> None:
    state = asyncio.run(read_current_security_mode(None))
    assert state["mode"] == "UNKNOWN"


def test_security_state_defaults_to_normal_before_first_transition() -> None:
    state = asyncio.run(read_current_security_mode(FakeModePool(None)))
    assert state["mode"] == "NORMAL"
    assert state["transition_id"] is None
