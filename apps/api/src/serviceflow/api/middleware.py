"""Request correlation and structured access logging (PRD 43).

Written as raw ASGI middleware rather than Starlette's `BaseHTTPMiddleware` on
purpose. `BaseHTTPMiddleware` runs the downstream app in a separate anyio task,
which gives it its own copy of the context - so `user_id` and `organization_id`
set by the auth dependency never propagated back, and every authenticated
request logged them as absent. A plain ASGI callable shares the context, so the
values the dependency sets are visible here when the response is logged.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from serviceflow.core import context

logger = logging.getLogger("serviceflow.access")

# Header names are matched lower-case in ASGI.
_REQUEST_ID_HEADER = b"x-request-id"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or {}).get(_REQUEST_ID_HEADER)
        request_id = incoming.decode("latin-1")[:64] if incoming else f"req_{uuid.uuid4().hex[:16]}"
        context.bind_request(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers") or [])
                # Error responses set it themselves; do not send it twice.
                if not any(name == _REQUEST_ID_HEADER for name, _ in headers):
                    headers.append((_REQUEST_ID_HEADER, request_id.encode("latin-1")))
                    message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "request failed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)

        logger.info(
            "request",
            extra={
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status_code,
                "duration_ms": duration_ms,
                # Set by the auth dependency. Visible here because the context
                # holds one mutable dict rather than a value per task copy.
                "user_id": context.user_id(),
                "organization_id": context.organization_id(),
            },
        )
