"""Server-Sent Events (PRD 17).

SSE rather than WebSockets: everything here flows server to client, and the PRD
asks for the simpler primitive unless bidirectional traffic is actually needed.

Authorization happens on the connection, not per message. The caller is resolved
by the same dependency every other route uses - the session token arrives as a
bearer header from the Next.js proxy, so the cookie stays httpOnly and no token
is put where JavaScript can read it. The stream then subscribes only to the
caller's own organization channel and drops any event the caller may not see, so
one connection can never observe another tenant's activity.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from serviceflow.api.deps import ActiveUser, AppSettings
from serviceflow.services import realtime

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])


async def _stream(
    request: Request, current_user: ActiveUser, keepalive_seconds: int
) -> AsyncIterator[bytes]:
    # Tells the browser's EventSource how long to wait before reconnecting.
    yield b"retry: 3000\n\n"
    yield b": connected\n\n"

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)

    async def pump() -> None:
        try:
            async for event in realtime.subscribe(current_user.organization_id):
                if not event.visible_to(
                    user_id=current_user.user_id,
                    roles=[role.value for role in current_user.roles],
                ):
                    continue
                try:
                    queue.put_nowait(event.to_json())
                except asyncio.QueueFull:
                    # A client this far behind will refetch on its own; dropping
                    # is better than growing an unbounded buffer.
                    logger.warning("realtime queue full; dropping an event")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("realtime subscription ended", exc_info=True)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                # Keeps proxies from closing an idle connection.
                yield b": keepalive\n\n"
                continue

            yield f"data: {payload}\n\n".encode()

            if pump_task.done() and queue.empty():
                break
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task


@router.get("/events", summary="Realtime event stream")
async def events(
    request: Request, current_user: ActiveUser, settings: AppSettings
) -> StreamingResponse:
    """Lightweight envelopes only - the client refetches the record it names."""
    return StreamingResponse(
        _stream(request, current_user, settings.sse_keepalive_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx and friends buffer streamed responses unless told not to.
            "X-Accel-Buffering": "no",
        },
    )
