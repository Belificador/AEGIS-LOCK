import asyncio
from datetime import datetime, timedelta, timezone

from backend.services import temporary_pins
from backend.services.postgres_client import postgres_service


def _pin(pin_id: str, *, target_user: str = "visitante-17") -> dict:
    return {
        "id": pin_id,
        "door_name": "Puerta Lobby",
        "target_user": target_user,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
    }


def test_argus_revoke_by_door_and_user_audits_selected_pin(monkeypatch) -> None:
    pin = _pin("00000000-0000-0000-0000-000000000042")
    audits = []
    deactivated = []

    async def list_pins(*, limit, include_inactive=False):
        assert limit == 200
        assert include_inactive is False
        return [pin]

    async def deactivate_and_audit(pin_id, *, performed_by):
        deactivated.append(pin_id)
        audits.append({
            "action": "PIN_REVOKED",
            "performed_by": performed_by,
            "details": {"pin_id": pin_id, "door_name": pin["door_name"]},
        })
        return {**pin, "is_active": False}

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "list_temporary_pins", list_pins)
    monkeypatch.setattr(postgres_service, "deactivate_temporary_pin_and_audit", deactivate_and_audit)

    result = asyncio.run(temporary_pins.revoke_temporary_pin(
        created_by="admin-1",
        door_name="Puerta Lobby",
        target_user="VISITANTE-17",
    ))

    assert result["revoked"] is True
    assert result["pin_id"] == pin["id"]
    assert deactivated == [pin["id"]]
    assert audits[0]["action"] == "PIN_REVOKED"
    assert audits[0]["performed_by"] == "admin-1"


def test_argus_does_not_revoke_ambiguous_pin_match(monkeypatch) -> None:
    pins = [
        _pin("00000000-0000-0000-0000-000000000042"),
        _pin("00000000-0000-0000-0000-000000000043"),
    ]
    deactivated = []
    audits = []

    async def list_pins(*, limit, include_inactive=False):
        return pins

    async def deactivate_and_audit(pin_id, *, performed_by):
        deactivated.append(pin_id)
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "list_temporary_pins", list_pins)
    monkeypatch.setattr(postgres_service, "deactivate_temporary_pin_and_audit", deactivate_and_audit)

    result = asyncio.run(temporary_pins.revoke_temporary_pin(
        created_by="admin-1",
        door_name="Puerta Lobby",
        target_user="visitante-17",
    ))

    assert result["ambiguous"] is True
    assert len(result["matches"]) == 2
    assert deactivated == []
    assert audits == []
