import asyncio
from datetime import datetime, timedelta, timezone

from backend.config import Settings
from backend.core import pin_security
from backend.models.schemas import PinGenerateRequest
from backend.services import temporary_pins
from backend.services.postgres_client import postgres_service


def test_concurrent_pin_generation_retries_if_atomic_insert_loses_collision(monkeypatch) -> None:
    class AtomicPinStore:
        def __init__(self):
            self.lock = asyncio.Lock()
            self.hashes = set()
            self.rows = []

        async def create_if_available(self, **values):
            async with self.lock:
                await asyncio.sleep(0)
                if values["pin_hash"] in self.hashes:
                    return None
                self.hashes.add(values["pin_hash"])
                row = {
                    **values,
                    "id": values["pin_id"],
                    "created_at": datetime.now(timezone.utc),
                    "is_active": True,
                }
                self.rows.append(row)
                audits.append({
                    "action": "PIN_GENERATED",
                    "performed_by": values["created_by"],
                    "details": {
                        "pin_id": row["id"],
                        "door_name": row["door_name"],
                        "target_user": row["target_user"],
                    },
                })
                return row

    store = AtomicPinStore()
    audits = []
    settings = Settings(jwt_secret="test-secret-material-which-is-long-enough", pin_code_length=4)
    candidate_codes = iter((42, 42, 43))

    monkeypatch.setattr(temporary_pins, "get_settings", lambda: settings)
    monkeypatch.setattr(pin_security, "get_settings", lambda: settings)
    monkeypatch.setattr(temporary_pins.secrets, "randbelow", lambda _limit: next(candidate_codes))
    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "create_temporary_pin_if_hash_available", store.create_if_available)

    payloads = [
        PinGenerateRequest(door_name="Puerta Lobby", duration_hours=8, target_user="visitante-1"),
        PinGenerateRequest(door_name="Puerta Lobby", duration_hours=8, target_user="visitante-2"),
    ]

    async def generate_both():
        return await asyncio.gather(*(
            temporary_pins.generate_temporary_pin(payload, created_by="admin")
            for payload in payloads
        ))

    created = asyncio.run(generate_both())

    assert {pin.pin_code for pin in created} == {"0042", "0043"}
    assert len(store.hashes) == 2
    assert len(audits) == 2
