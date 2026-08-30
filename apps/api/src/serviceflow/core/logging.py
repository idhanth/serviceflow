"""Structured JSON logging (PRD 43).

Never emits passwords, tokens or full secrets: only the allow-listed fields below
plus whatever a call site passes explicitly.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from serviceflow.core import context

_REDACTED = "[redacted]"
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "secret",
        "jwt_secret",
        "clerk_secret_key",
        "api_key",
        "cookie",
    }
)


class ContextJsonFormatter(JsonFormatter):
    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.fromtimestamp(record.created, UTC).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        for key, value in context.current_context().items():
            log_record.setdefault(key, value)
        for key in list(log_record):
            if key.lower() in _SENSITIVE_KEYS:
                log_record[key] = _REDACTED
        log_record.pop("taskName", None)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ContextJsonFormatter("%(timestamp)s %(level)s %(logger)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn duplicates access logs in its own format; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
