"""Check catalogued camera feeds without accepting arbitrary URLs from Argus."""

from time import time

import httpx

from backend.config import get_settings
from backend.services.camera_catalog import CAMERA_BY_ID, signed_camera_url


async def verify_camera_feed(camera_id: str) -> dict[str, object]:
    camera = CAMERA_BY_ID.get(camera_id)
    settings = get_settings()
    if camera is None:
        return {"camera_id": camera_id, "available": False, "status": "unknown_camera"}
    feed_url = signed_camera_url(
        camera_id,
        base_url=settings.gemelo_media_base_url,
        secret=settings.telemetry_api_key or "",
        expires_at=int(time()) + 60,
    )
    if not feed_url:
        return {"camera_id": camera_id, "zone": camera["zone"], "available": False, "status": "not_configured"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5, connect=2), follow_redirects=False) as client:
            async with client.stream("GET", feed_url, headers={"Range": "bytes=0-0"}) as response:
                content_type = response.headers.get("content-type", "").lower()
                available = response.status_code in {200, 206} and (
                    content_type.startswith("video/") or "octet-stream" in content_type
                )
                if available:
                    async for _chunk in response.aiter_bytes():
                        break
                status = "available" if available else f"http_{response.status_code}"
    except httpx.HTTPError:
        available = False
        status = "unreachable"
    return {"camera_id": camera_id, "zone": camera["zone"], "available": available, "status": status}
