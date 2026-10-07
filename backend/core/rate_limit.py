from hashlib import sha256
import time
from redis.asyncio import Redis
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.config import get_settings
from backend.core.security import decode_access_token

_settings = get_settings()
_storage_uri = _settings.rate_limit_storage_uri or "memory://"


def rate_limit_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        try:
            subject = decode_access_token(authorization.removeprefix("Bearer ")).get("sub")
            if subject:
                return f"user:{subject}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_identity, storage_uri=_storage_uri, strategy="moving-window")


class WebSocketRateLimiter:
    """Shared fixed-window limits for WebSocket handshakes and frames."""

    _INCREMENT_SCRIPT = """
    local hits = redis.call('INCR', KEYS[1])
    if hits == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
    return hits
    """

    def __init__(self, storage_uri: str) -> None:
        self._redis: Redis | None = Redis.from_url(storage_uri, decode_responses=True) if storage_uri.startswith(("redis://", "rediss://")) else None
        self._memory: dict[tuple[str, int], int] = {}

    async def allow(self, identity: str, action: str, *, limit: int, window_seconds: int) -> bool:
        slot = int(time.time()) // window_seconds
        digest = sha256(f"{action}\0{identity}".encode("utf-8")).hexdigest()
        key = f"aegis:ws-rate:{digest}:{slot}"
        if self._redis is not None:
            hits = await self._redis.eval(self._INCREMENT_SCRIPT, 1, key, window_seconds * 2)
            return int(hits) <= limit

        memory_key = (key, slot)
        hits = self._memory.get(memory_key, 0) + 1
        self._memory[memory_key] = hits
        if len(self._memory) > 4096:
            self._memory = {entry: count for entry, count in self._memory.items() if entry[1] >= slot - 1}
        return hits <= limit

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
