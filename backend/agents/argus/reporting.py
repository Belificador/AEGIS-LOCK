"""Privacy-minimized data views exposed as Argus read tools."""

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.argus_reporting import summarize_window


async def get_activity_summary(days: int = 1) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    return await summarize_window(end - timedelta(days=days), end)


async def get_current_status() -> dict[str, Any]:
    summary = await get_activity_summary(1)
    return {
        "temperature_c": summary["temperature_c"]["last"],
        "voltage_v": summary["voltage_v"]["last"],
        "power_kw": summary["power_kw_last"],
        "energy_kwh": summary["energy_kwh_last"],
        "occupancy": summary["occupancy"]["current_total"],
        "alerts_today": summary["readings_with_alerts"],
        "window_start": summary["start"],
        "window_end": summary["end"],
    }
