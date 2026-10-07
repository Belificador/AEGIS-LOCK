"""Small ASGI middleware for request limits and baseline browser protections."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersAndSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method in {"POST", "PUT", "PATCH"} and path.startswith("/api/"):
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            if content_type != b"application/json":
                await self._reject(send, status=415, detail="Content-Type must be application/json")
                return
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.max_request_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(send)
                return

        # Buffer bounded JSON request bodies before handing them to FastAPI. This also
        # enforces the limit when a client omits Content-Length or uses chunked input.
        buffered_messages: list[Message] = []
        body_size = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > self.max_request_bytes:
                    await self._reject(send)
                    return
                if not message.get("more_body", False):
                    break

        async def replay_receive() -> Message:
            if buffered_messages:
                return buffered_messages.pop(0)
            return await receive()

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, replay_receive, send_with_security_headers)

    @staticmethod
    async def _reject(send: Send, *, status: int = 413, detail: str = "Request body too large") -> None:
        body = ('{"detail":"' + detail + '"}').encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
