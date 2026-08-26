"""Reject oversized Sydney ingest bodies before JSON decoding."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _ContextEventBatchTooLarge(Exception):
    pass


class ContextEventBatchLimitMiddleware:
    """Apply a streaming byte cap to the single durable-event ingest route."""

    _PATH = "/api/v1/agent-control/context/events/batch"

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "sydney_context_event_batch_too_large"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != self._PATH
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > self.max_bytes:
                await self._reject(scope, receive, send)
                return

        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise _ContextEventBatchTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _ContextEventBatchTooLarge:
            await self._reject(scope, receive, send)
