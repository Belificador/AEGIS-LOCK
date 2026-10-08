"""Camera IDs and signed media URLs shared by the AEGIS camera UI."""

import hashlib
import hmac
from urllib.parse import quote


CAMERAS: tuple[dict[str, str], ...] = (
    {"camera_id": "CAM_01_GERENCIA", "name": "Administración", "zone": "Administración", "video_path": "assets/cameras/administracion/feed.mp4"},
    {"camera_id": "CAM_02_CONFERENCIAS", "name": "Conferencias", "zone": "Sala de Conferencias", "video_path": "assets/cameras/conferencias/feed.mp4"},
    {"camera_id": "CAM_03_OFICINA_L1", "name": "Oficina L1", "zone": "Oficina L1", "video_path": "assets/cameras/oficina_l1/feed.mp4"},
    {"camera_id": "CAM_04_OFICINA_R1", "name": "Gerencia", "zone": "Gerencia", "video_path": "assets/cameras/gerencia/feed.mp4"},
    {"camera_id": "CAM_05_OFICINA_L2", "name": "Oficina L2", "zone": "Oficina L2", "video_path": "assets/cameras/oficina_l2/feed.mp4"},
    {"camera_id": "CAM_06_PASILLO_NORTE", "name": "Pasillo norte", "zone": "Pasillo norte", "video_path": "assets/cameras/pasillo_1/feed.mp4"},
    {"camera_id": "CAM_07_PASILLO_SUR", "name": "Pasillo sur", "zone": "Pasillo sur", "video_path": "assets/cameras/pasillo_2/feed.mp4"},
    {"camera_id": "CAM_08_RECEPCION", "name": "Recepción", "zone": "Recepción", "video_path": "assets/cameras/recepcion/feed.mp4"},
    {"camera_id": "CAM_09_OFICINA_L3", "name": "Oficina L3", "zone": "Oficina L3", "video_path": "assets/cameras/oficina_l3/feed.mp4"},
)

CAMERA_BY_ID = {camera["camera_id"]: camera for camera in CAMERAS}


def signed_camera_url(camera_id: str, *, base_url: str, secret: str, expires_at: int) -> str | None:
    if camera_id not in CAMERA_BY_ID or not base_url or not secret:
        return None
    message = f"{camera_id}:{expires_at}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return (
        f"{base_url.rstrip('/')}/camera-feed/{quote(camera_id, safe='')}"
        f"?expires={expires_at}&sig={signature}"
    )
