import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from backend.services import argus_reporting
from backend.services.postgres_client import postgres_service


def test_recent_activity_merges_motion_audit_and_errors_without_personal_data(monkeypatch) -> None:
    now = datetime.now(timezone.utc)

    class ActivityPool:
        async def fetch(self, query, limit):
            assert limit == 10
            if "FROM security_events" in query:
                return [{
                    "received_at": now - timedelta(minutes=3),
                    "event": {"event_type": "motion_detected", "zone": "Gerencia", "valor": "visitor-private"},
                    "alerts": [],
                }]
            if "FROM audit_logs" in query:
                return [{
                    "timestamp": now - timedelta(minutes=2),
                    "action": "PIN_ACCESS_DENIED",
                    "details": {"zone": "Recepción", "target_user": "visitor-private"},
                }]
            return [{"timestamp": now - timedelta(minutes=1), "error_type": "WebSocket Disconnect"}]

    monkeypatch.setattr(postgres_service, "pool", ActivityPool())
    activities = asyncio.run(argus_reporting.get_recent_activity(10))

    assert [entry["activity"] for entry in activities] == [
        "Error de sistema · WebSocket Disconnect",
        "Acceso denegado",
        "Movimiento detectado",
    ]
    assert activities[1]["zone"] == "Recepción"
    assert "visitor-private" not in json.dumps(activities)
    assert all("performed_by" not in entry for entry in activities)


def test_recent_activity_caps_requested_rows_to_twenty(monkeypatch) -> None:
    limits = []

    class EmptyPool:
        async def fetch(self, _query, limit):
            limits.append(limit)
            return []

    monkeypatch.setattr(postgres_service, "pool", EmptyPool())
    activities = asyncio.run(argus_reporting.get_recent_activity(500))

    assert activities == []
    assert limits == [20, 20, 20]
