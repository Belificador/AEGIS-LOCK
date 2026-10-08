import asyncio
import json

from backend.routers.ws_manager import ConnectionManager


def test_manager_publishes_live_payload_and_caches_without_signed_feed_url() -> None:
    class RedisStub:
        def __init__(self):
            self.values = {}
            self.published = []
            self.stream_entries = []

        async def set(self, key, value, *, ex):
            self.values[key] = (value, ex)

        async def publish(self, channel, value):
            self.published.append((channel, value))
            return 1

        async def xadd(self, stream, fields):
            self.stream_entries.append((stream, fields))
            return "1-0"

        async def get(self, key):
            return self.values[key][0]

        async def aclose(self):
            return None

    async def exercise():
        manager = ConnectionManager()
        redis = RedisStub()
        manager._redis = redis
        payload = {
            "kind": "telemetry",
            "event": {"event_id": "event-1", "metadata": {"feed_url": "https://media.test/signed"}},
            "alerts": [],
        }

        await manager.broadcast(payload)
        queued = await manager.enqueue_persistence({"event_id": "event-1"}, [])
        cached = await manager.latest_cached_event()
        await manager.close()
        return redis, cached, queued

    redis, cached, queued = asyncio.run(exercise())

    assert redis.published[0][0] == "aegis:telemetry:live:v1"
    assert json.loads(redis.published[0][1]) == {
        "kind": "telemetry",
        "event": {"event_id": "event-1", "metadata": {"feed_url": "https://media.test/signed"}},
        "alerts": [],
    }
    assert cached["event"]["event_id"] == "event-1"
    assert "feed_url" not in cached["event"]["metadata"]
    assert queued is True
    assert redis.stream_entries[0][0] == "aegis:telemetry:persist:v1"
    assert json.loads(redis.stream_entries[0][1]["event"]) == {"event_id": "event-1"}
