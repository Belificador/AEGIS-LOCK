from hashlib import sha256
import hmac
from urllib.parse import parse_qs, urlparse

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
