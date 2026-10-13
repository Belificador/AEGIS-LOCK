import asyncio

from backend.routers.ws_manager import ConnectionManager


class RecordingSocket:
    def __init__(self):
        self.messages = []
        self.close_codes = []

    async def send_json(self, message):
        await asyncio.sleep(0)
        self.messages.append(message)

    async def close(self, code):
        self.close_codes.append(code)


def test_concurrent_broadcasts_reach_every_connected_dashboard() -> None:
    manager = ConnectionManager()
    clients = [RecordingSocket() for _ in range(8)]
    messages = [{"sequence": number} for number in range(40)]

    async def exercise():
        await asyncio.gather(*(manager.add(client) for client in clients))
        await asyncio.gather(*(manager.broadcast(message) for message in messages))

    asyncio.run(exercise())

    expected = set(range(len(messages)))
    for client in clients:
        received = [message["sequence"] for message in client.messages]
        assert len(received) == len(messages)
        assert set(received) == expected


def test_broken_dashboard_is_removed_without_blocking_healthy_clients() -> None:
    class BrokenSocket(RecordingSocket):
        async def send_json(self, _message):
            raise RuntimeError("simulated socket failure")

    manager = ConnectionManager()
    healthy = RecordingSocket()
    broken = BrokenSocket()

    async def exercise():
        await manager.add(healthy)
        await manager.add(broken)
        await manager.broadcast({"sequence": 1})

    asyncio.run(exercise())

    assert healthy.messages == [{"sequence": 1}]
    assert broken.close_codes == [1011]
    assert manager.active_connections == {healthy}
