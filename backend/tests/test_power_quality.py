import asyncio

import pytest
from pydantic import ValidationError

from backend.models.schemas import TelemetryEvent
from backend.services import rules_engine


def test_missing_voltage_is_not_a_power_loss_and_typed_voltage_requires_a_reading() -> None:
    generic = TelemetryEvent(source_id="meter-01", event_type="telemetry", voltage_v=None)
    assert "POWER_LOSS" not in {alert["code"] for alert in rules_engine.evaluate_event(generic)}

    with pytest.raises(ValidationError, match="lectura numérica explícita"):
        TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=None)


def test_only_explicit_zero_voltage_triggers_power_loss() -> None:
    outage = TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=0)
    normal = TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=220)

    assert "POWER_LOSS" in {alert["code"] for alert in rules_engine.evaluate_event(outage)}
    assert "POWER_LOSS" not in {alert["code"] for alert in rules_engine.evaluate_event(normal)}


def test_voltage_fluctuation_alerts_on_first_out_of_range_transition() -> None:
    class FakePool:
        def __init__(self, previous):
            self.previous = previous

        async def fetchrow(self, *_args):
            return None if self.previous is None else {"voltage_v": self.previous}

    event = TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=105)

    alert_on_first_out_of_range_sample = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool(220), zone="Lobby")
    )
    no_repeat_during_same_excursion = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool(108), zone="Lobby")
    )
    alert_on_new_excursion = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool(230), zone="Lobby")
    )
    upper_band_warning = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(
            TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=221),
            pool=FakePool(220),
            zone="Lobby",
        )
    )
    normal_boundary = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(
            TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=110),
            pool=FakePool(105),
            zone="Lobby",
        )
    )

    assert alert_on_first_out_of_range_sample == {
        "severity": "warning",
        "code": "VOLTAGE_FLUCTUATION",
        "message": "Fluctuación de voltaje: 105.0 V fuera del rango normal 110–220 V en Lobby",
    }
    assert no_repeat_during_same_excursion is None
    assert alert_on_new_excursion["code"] == "VOLTAGE_FLUCTUATION"
    assert upper_band_warning is not None and upper_band_warning["code"] == "VOLTAGE_FLUCTUATION"
    assert normal_boundary is None
