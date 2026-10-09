import asyncio
from datetime import datetime, timezone

from backend.services import argus_reporting


def test_argus_report_uses_aggregates_and_preserves_real_zero_values(monkeypatch) -> None:
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    end = datetime(2026, 10, 9, tzinfo=timezone.utc)

    class FakeDatabase:
        async def fetchrow(self, query, *_args):
            if "PIN_VALIDATED" in query:
                return {"validations": 1, "distinct_people": 1}
            return {
                "readings": 3,
                "temperature_min": 21.0,
                "temperature_max": 29.0,
                "temperature_avg": 25.0,
                "voltage_min": 0.0,
                "voltage_max": 220.0,
                "power_loss_events": 1,
                "occupancy_peak": 0,
                "occupancy_average": 0.0,
                "pin_access_events": 1,
                "authorized_accesses": 1,
                "denied_accesses": 0,
                "entries": 1,
                "exits": 0,
                "accesses_without_direction": 0,
                "readings_with_alerts": 1,
            }

        async def fetchval(self, _query, *_args):
            if len(_args) == 2:
                return 1
            field = _args[2]
            return {"temperature_c": 25, "voltage_v": 0, "power_kw": 0, "energy_kwh": 0, "occupancy": 0}[field]

        async def fetch(self, *_args):
            return [{"zone": "Recepción", "occupancy": "0"}]

    summary = asyncio.run(argus_reporting.summarize_window(start, end, pool=FakeDatabase()))

    assert summary["temperature_c"]["last"] == 25
    assert summary["voltage_v"]["last"] == 0
    assert summary["occupancy"]["current_total"] == 0
    assert summary["power_kw_last"] == 0
    assert summary["access"]["authorized"] == 1
    assert "Personas presentes (último aforo por zona): 0" in argus_reporting.format_report_facts(summary)


def test_argus_recent_activity_redacts_unknown_zone_and_raw_person_data(monkeypatch) -> None:
    class FakePool:
        async def fetch(self, *_args):
            return [{
                "received_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
                "event": {
                    "tipo_evento": "acceso_pin",
                    "valor": "GRANTED",
                    "zona": "visitante secreto",
                    "metadata": {"target_user": "Nombre Privado"},
                },
                "alerts": [],
            }]

    monkeypatch.setattr(argus_reporting.postgres_service, "pool", FakePool())
    result = asyncio.run(argus_reporting.get_recent_activity())

    assert result[0]["activity"] == "Acceso autorizado"
    assert result[0]["zone"] == "Otra zona"
    assert "Nombre Privado" not in repr(result)
    assert "visitante secreto" not in repr(result)
