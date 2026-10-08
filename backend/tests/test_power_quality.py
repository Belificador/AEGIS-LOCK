import asyncio
from types import SimpleNamespace

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


def test_voltage_fluctuation_requires_three_consecutive_out_of_range_samples(monkeypatch) -> None:
    class FakePool:
        def __init__(self, values):
            self.values = values

        async def fetch(self, *_args):
            return [{"voltage_v": value} for value in self.values]

    monkeypatch.setattr(
        rules_engine,
        "get_settings",
        lambda: SimpleNamespace(
            voltage_normal_min_v=110,
            voltage_normal_max_v=220,
            voltage_fluctuation_samples=3,
        ),
    )
    event = TelemetryEvent(source_id="meter-01", event_type="voltage", voltage_v=105)

    alert_on_third_sample = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool([108, 106]), zone="Lobby")
    )
    no_alert_before_threshold = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool([108, 112]), zone="Lobby")
    )
    alert_stays_active_while_out_of_range = asyncio.run(
        rules_engine.evaluate_voltage_fluctuation(event, pool=FakePool([108, 106, 105]), zone="Lobby")
    )

    assert alert_on_third_sample == {
        "severity": "warning",
        "code": "VOLTAGE_FLUCTUATION",
        "message": "Fluctuación de voltaje: 105.0 V fuera del rango normal 110–220 V en Lobby",
    }
    assert no_alert_before_threshold is None
    assert alert_stays_active_while_out_of_range is not None
    assert alert_stays_active_while_out_of_range["code"] == "VOLTAGE_FLUCTUATION"
