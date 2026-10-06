"""Authenticated camera catalogue and short-lived Render media URLs."""

from time import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from backend.config import get_settings
from backend.core.dependencies import require_operator
from backend.services.camera_catalog import CAMERAS, signed_camera_url

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("")
async def camera_catalog(
    _: Annotated[dict[str, Any], Depends(require_operator)],
) -> list[dict[str, str]]:
    return [
        {"camera_id": camera["camera_id"], "zone": camera["zone"]}
        for camera in CAMERAS
    ]


@router.get("/{camera_id}/feed-url")
async def camera_feed_url(
    camera_id: str,
    _: Annotated[dict[str, Any], Depends(require_operator)],
) -> dict[str, Any]:
    settings = get_settings()
    expires_at = int(time()) + 3600
    feed_url = signed_camera_url(
        camera_id,
        base_url=settings.gemelo_media_base_url,
        secret=settings.telemetry_api_key or "",
        expires_at=expires_at,
    )
    if feed_url is None:
        raise HTTPException(status_code=404, detail="Cámara no encontrada o relay multimedia no configurado")
    return {"camera_id": camera_id, "feed_url": feed_url, "expires_at": expires_at}
