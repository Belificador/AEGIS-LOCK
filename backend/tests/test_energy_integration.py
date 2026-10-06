from datetime import datetime, timedelta, timezone

from backend.services.postgres_client import integrate_energy_kwh


def test_integrates_previous_power_over_elapsed_time() -> None:
    start = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    result = integrate_energy_kwh(1.25, 1.5, start, start + timedelta(hours=2))
    assert result == 4.25


def test_nonpositive_elapsed_interval_never_subtracts_energy() -> None:
    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    assert integrate_energy_kwh(3.0, 2.0, now + timedelta(minutes=1), now) == 3.0
