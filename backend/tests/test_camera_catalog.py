from hashlib import sha256
import hmac
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.core.security import create_access_token
from backend.main import app
from backend.routers import cameras
from backend.services.postgres_client import postgres_service
from backend.services.camera_catalog import CAMERA_BY_ID, signed_camera_url


def test_camera_catalog_signs_only_known_gemelo_routes() -> None:
    expires = 1_800_000_000
    url = signed_camera_url(
        "CAM_03_OFICINA_L1",
        base_url="https://gemelo.example.test/",
        secret="telemetry-server-secret",
        expires_at=expires,
    )
    assert url is not None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/camera-feed/CAM_03_OFICINA_L1")
    expected = hmac.new(
        b"telemetry-server-secret",
        f"CAM_03_OFICINA_L1:{expires}".encode(),
        sha256,
    ).hexdigest()
    assert query["sig"] == [expected]
    assert signed_camera_url("CAM_99_UNKNOWN", base_url="https://gemelo.example.test", secret="x", expires_at=expires) is None
    assert len(CAMERA_BY_ID) == 9


def test_operator_keeps_read_only_access_to_camera_feeds(monkeypatch) -> None:
    async def no_connect(*_args, **_kwargs):
        return None

    async def no_close():
        return None

    monkeypatch.setattr(postgres_service, "connect", no_connect)
    monkeypatch.setattr(postgres_service, "close", no_close)
    monkeypatch.setattr(cameras, "get_settings", lambda: Settings(
        gemelo_media_base_url="https://gemelo.example.test",
        telemetry_api_key="t" * 40,
    ))
    token, _ = create_access_token(subject="operador", role="operator")

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        catalog = client.get("/api/v1/cameras", headers=headers)
        feed = client.get("/api/v1/cameras/CAM_03_OFICINA_L1/feed-url", headers=headers)

    assert catalog.status_code == 200
    assert any(camera["camera_id"] == "CAM_03_OFICINA_L1" for camera in catalog.json())
    assert feed.status_code == 200
    assert feed.json()["feed_url"].startswith("https://gemelo.example.test/")
