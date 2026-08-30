"""Per-request correlation, propagated into logs without threading it through calls.

The values live in a *mutable dict* held by one ContextVar, rather than in a
ContextVar each. That is deliberate. FastAPI runs synchronous dependencies and
endpoints with `run_in_threadpool`, which copies the context; a `ContextVar.set()`
performed there updates the copy and is thrown away when the worker returns. So
the actor set by the auth dependency never reached the access log - every
authenticated request logged `user_id: null`.

Binding the dict once, in the ASGI middleware, before any child context forks
means every copy points at the same object, so a write from a worker thread is
visible to the middleware that logs the response.
"""

from __future__ import annotations

from contextvars import ContextVar

_context: ContextVar[dict[str, str] | None] = ContextVar("serviceflow_context", default=None)


def bind_request(request_id: str) -> None:
    """Start a fresh context for one request. Call before any work forks off."""
    _context.set({"request_id": request_id})


def bind_actor(user_id: str, organization_id: str) -> None:
    """Record who the request turned out to be.

    Mutates the bound dict in place, which is what makes this visible from the
    threadpool worker the auth dependency runs in.
    """
    values = _context.get()
    if values is None:
        values = {}
        _context.set(values)
    values["user_id"] = user_id
    values["organization_id"] = organization_id


def reset_request_context() -> None:
    """Drop every correlation value, so nothing bleeds into the next request."""
    _context.set(None)


def request_id() -> str | None:
    return (_context.get() or {}).get("request_id")


def user_id() -> str | None:
    return (_context.get() or {}).get("user_id")


def organization_id() -> str | None:
    return (_context.get() or {}).get("organization_id")


def current_context() -> dict[str, str]:
    """The correlation fields worth carrying into background work."""
    return {key: value for key, value in (_context.get() or {}).items() if value}


def adopt_context(values: dict[str, str] | None) -> None:
    """Take on correlation fields handed over from another process.

    Used by Celery tasks so their log lines carry the request_id of whatever
    caused the work, rather than starting a fresh, untraceable story.
    """
    allowed = ("request_id", "user_id", "organization_id")
    adopted = {key: values[key] for key in allowed if values and values.get(key)}
    _context.set(adopted or None)
