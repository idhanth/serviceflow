"""Liveness, readiness and infrastructure visibility (PRD 44)."""

from __future__ import annotations

import logging
from typing import Any

import redis
from fastapi import APIRouter, Response, status
from sqlalchemy import func, select, text

from serviceflow.api.deps import AdminUser, AppSettings, DbSession
from serviceflow.db.models.enums import NotificationChannel, NotificationStatus
from serviceflow.db.models.notification import Notification
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services.realtime import CHANNEL_PREFIX

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the process is up")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: dependencies are reachable")
def ready(db: DbSession, settings: AppSettings, response: Response) -> dict[str, object]:
    """PostgreSQL and Redis both have to answer.

    Redis is required: it is the Celery broker and the realtime bus. The API
    still serves database-backed reads without it, but it is not *ready* -
    emails would only queue in the outbox and realtime would be dark.
    """
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

    ready_now = all(value == "ok" for value in checks.values())
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}


@router.get(
    "/api/v1/infrastructure",
    response_model=DataResponse[dict[str, Any]],
    summary="Queue and delivery health",
)
def infrastructure(
    current_user: AdminUser, db: DbSession, settings: AppSettings
) -> DataResponse[dict[str, Any]]:
    """Operational counters an admin can act on: stuck email, dark realtime.

    Scoped to the caller's organization, so it reports on their shop rather than
    the deployment.
    """

    def count(status_value: NotificationStatus) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.organization_id == current_user.organization_id,
                    Notification.channel == NotificationChannel.EMAIL,
                    Notification.status == status_value,
                )
            )
            or 0
        )

    email = {
        "pending": count(NotificationStatus.PENDING),
        "sent": count(NotificationStatus.SENT),
        "failed": count(NotificationStatus.FAILED),
    }

    queue: dict[str, object] = {"reachable": False}
    realtime_health: dict[str, object] = {"reachable": False, "subscribers": 0}

    client = redis.Redis.from_url(str(settings.redis_url), socket_connect_timeout=2)
    try:
        client.ping()
        queue = {
            "reachable": True,
            # Celery's default queue is a Redis list; its length is the backlog.
            "depth": int(client.llen("celery") or 0),
        }
        channel = f"{CHANNEL_PREFIX}:{current_user.organization_id}"
        subscribers = client.pubsub_numsub(channel)
        realtime_health = {
            "reachable": True,
            "subscribers": int(subscribers[0][1]) if subscribers else 0,
        }
    except Exception:
        logger.warning("infrastructure probe: redis unreachable")
    finally:
        client.close()

    return DataResponse[dict[str, Any]](
        data={"email": email, "queue": queue, "realtime": realtime_health}
    )
