"""Liveness and readiness probes (PRD 44)."""

from __future__ import annotations

import logging

import redis
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from serviceflow.api.deps import AppSettings, DbSession

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the process is up")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: dependencies are reachable")
def ready(db: DbSession, settings: AppSettings, response: Response) -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("readiness: database unreachable")
        checks["database"] = "unavailable"

    client = redis.Redis.from_url(str(settings.redis_url), socket_connect_timeout=2)
    try:
        client.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.exception("readiness: redis unreachable")
        checks["redis"] = "unavailable"
    finally:
        client.close()

    ready_now = all(v == "ok" for v in checks.values())
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
