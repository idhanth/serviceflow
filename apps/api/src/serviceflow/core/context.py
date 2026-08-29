"""Per-request context propagated into logs without threading it through calls."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
organization_id_var: ContextVar[str | None] = ContextVar("organization_id", default=None)
