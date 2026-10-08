"""Privacy-minimized data views exposed as Argus read tools."""

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.argus_reporting import get_current_building_mode, get_current_occupancy, summarize_window


async def get_activity_summary(days: int = 1) -> dict[str, Any]:
    end = datetime.now(timezone.utc)
    return await summarize_window(end - timedelta(days=days), end)


async def get_current_status() -> dict[str, Any]:
    summary = await get_activity_summary(1)
    occupancy = await get_current_occupancy()
    mode = await get_current_building_mode()
    return {
        "temperature_c": summary["temperature_c"]["last"],
        "voltage_v": summary["voltage_v"]["last"],
        "power_kw": summary["power_kw_last"],
        "energy_kwh": summary["energy_kwh_last"],
        "occupancy": occupancy["total"],
        "occupancy_by_zone": occupancy["by_zone"],
        "occupancy_updated_at": occupancy["updated_at"],
        "occupancy_stale": occupancy["stale"],
        "security_mode": mode["mode"],
        "security_mode_updated_at": mode["updated_at"],
        "security_modes_are_simulated": True,
        "alerts_today": summary["readings_with_alerts"],
        "window_start": summary["start"],
        "window_end": summary["end"],
    }
