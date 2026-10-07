import asyncio

from backend.core.rate_limit import WebSocketRateLimiter


def test_websocket_rate_limiter_caps_frames_per_identity_and_action() -> None:
    limiter = WebSocketRateLimiter("memory://")

    async def exercise() -> None:
        assert await limiter.allow("ip:127.0.0.1", "telemetry", limit=2, window_seconds=60)
        assert await limiter.allow("ip:127.0.0.1", "telemetry", limit=2, window_seconds=60)
        assert not await limiter.allow("ip:127.0.0.1", "telemetry", limit=2, window_seconds=60)
        assert await limiter.allow("ip:127.0.0.1", "dashboard", limit=2, window_seconds=60)

    asyncio.run(exercise())
