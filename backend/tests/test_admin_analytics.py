from fastapi.testclient import TestClient

from backend.core.security import create_access_token
from backend.main import app
from backend.services.postgres_client import postgres_service


def test_analytics_routes_are_admin_only_and_return_database_reports(monkeypatch) -> None:
    async def no_close():
        return None

    async def history(*, start, end, limit):
        return {"start": start.isoformat(), "end": end.isoformat(), "samples": [], "peaks": {}, "audit_logs": []}

    async def errors(*, limit, offset):
        return {"total": 0, "limit": limit, "offset": offset, "errors": []}

    async def no_error_log(**_values):
        return None

    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(postgres_service, "analytics_history", history)
    monkeypatch.setattr(postgres_service, "error_history", errors)
    monkeypatch.setattr(postgres_service, "write_error_log", no_error_log)
    admin, _ = create_access_token(subject="admin", role="admin")
    operator, _ = create_access_token(subject="operador", role="operator")

    with TestClient(app) as client:
        report = client.get("/api/v1/analytics/history?days=3", headers={"Authorization": f"Bearer {admin}"})
        logs = client.get("/api/v1/analytics/errors", headers={"Authorization": f"Bearer {admin}"})
        denied = client.get("/api/v1/analytics/errors", headers={"Authorization": f"Bearer {operator}"})

    assert report.status_code == 200 and report.json()["samples"] == []
    assert logs.status_code == 200 and logs.json()["total"] == 0
    assert denied.status_code == 403
