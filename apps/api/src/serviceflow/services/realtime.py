"""Realtime event fan-out over Redis pub/sub (PRD 17).

Events are **ephemeral signals, not durable state**. An envelope says only what
changed and who may know about it; the client answers by invalidating a query and
refetching from the database, which stays the single source of truth. That is
what makes a missed event harmless: a reconnecting client refetches and is
correct again without replaying anything.

Redis rather than an in-process emitter, so it keeps working with several API
processes and when a Celery worker is the thing raising the event.

Publishing never fails a request. A booking that committed has happened; if the
broadcast cannot go out, the durable state is still right and the client's next
refetch will show it.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

import redis
import redis.asyncio as aioredis

from serviceflow.core.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "sf:events"


# Staff who watch the whole business's queue receive its operational events.
OPERATIONS_ROLES = ("OWNER", "MANAGER", "DISPATCHER", "ANALYST")


def channel_for(organization_id: uuid.UUID | str) -> str:
    """One channel per tenant: a subscriber never even receives foreign traffic."""
    return f"{CHANNEL_PREFIX}:{organization_id}"


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """A signal that something changed. Carries no record content by design."""

    type: str  # notification.created | booking.updated | job.updated
    resource: str  # notification | booking | job
    resource_id: str
    organization_id: str
    # Explicit recipients, by user id. Empty means "role-addressed only".
    recipients: list[str] = field(default_factory=list)
    # Roles that also receive it, e.g. dispatchers for business-wide operational events.
    roles: list[str] = field(default_factory=list)
    occurred_at: str = ""

    def with_timestamp(self) -> RealtimeEvent:
        if self.occurred_at:
            return self
        return RealtimeEvent(
            type=self.type,
            resource=self.resource,
            resource_id=self.resource_id,
            organization_id=self.organization_id,
            recipients=self.recipients,
            roles=self.roles,
            occurred_at=datetime.now(UTC).isoformat(),
        )

    def visible_to(self, *, user_id: uuid.UUID, roles: Sequence[str]) -> bool:
        """Whether one connected client may receive this event."""
        if str(user_id) in self.recipients:
            return True
        return any(role in self.roles for role in roles)

    def to_json(self) -> str:
        return json.dumps(asdict(self.with_timestamp()), separators=(",", ":"))

    @staticmethod
    def from_json(raw: str) -> RealtimeEvent | None:
        try:
            payload = json.loads(raw)
            return RealtimeEvent(**payload)
        except (ValueError, TypeError):
            logger.warning("discarded malformed realtime event")
            return None


@lru_cache(maxsize=1)
def _publisher() -> redis.Redis[bytes]:
    return redis.Redis.from_url(
        str(get_settings().redis_url), socket_connect_timeout=2, socket_timeout=2
    )


def reset_publisher() -> None:
    """Test hook, for when settings change between cases."""
    _publisher.cache_clear()


def publish(event: RealtimeEvent) -> bool:
    """Broadcast one event. Returns False when it could not go out.

    Never raises: realtime is an optimisation over the durable record, and a
    failed broadcast must not turn a successful business action into an error.
    """
    try:
        _publisher().publish(channel_for(event.organization_id), event.to_json())
    except Exception:
        logger.warning(
            "realtime publish failed; clients will refetch on their own",
            extra={"event_type": event.type, "resource_id": event.resource_id},
        )
        return False
    return True


async def subscribe(organization_id: uuid.UUID) -> AsyncIterator[RealtimeEvent]:
    """Yield this organization's events until the caller stops listening."""
    client = aioredis.Redis.from_url(str(get_settings().redis_url))
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(channel_for(organization_id))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            raw = message["data"]
            event = RealtimeEvent.from_json(raw.decode() if isinstance(raw, bytes) else str(raw))
            if event is not None:
                yield event
    finally:
        await pubsub.close()
        await client.aclose()


# --------------------------------------------------------------- builders


def notification_created(
    *, organization_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
) -> RealtimeEvent:
    """Addressed to exactly one person, so no one else learns it exists."""
    return RealtimeEvent(
        type="notification.created",
        resource="notification",
        resource_id=str(notification_id),
        organization_id=str(organization_id),
        recipients=[str(user_id)],
    )


def booking_updated(
    *,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    customer_user_id: uuid.UUID | None = None,
    employee_user_id: uuid.UUID | None = None,
) -> RealtimeEvent:
    """The customer, the assigned technician, and every admin."""
    recipients = [str(i) for i in (customer_user_id, employee_user_id) if i is not None]
    return RealtimeEvent(
        type="booking.updated",
        resource="booking",
        resource_id=str(booking_id),
        organization_id=str(organization_id),
        recipients=recipients,
        roles=list(OPERATIONS_ROLES),
    )


def job_updated(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    customer_user_id: uuid.UUID | None = None,
    employee_user_id: uuid.UUID | None = None,
) -> RealtimeEvent:
    recipients = [str(i) for i in (customer_user_id, employee_user_id) if i is not None]
    return RealtimeEvent(
        type="job.updated",
        resource="job",
        resource_id=str(job_id),
        organization_id=str(organization_id),
        recipients=recipients,
        roles=list(OPERATIONS_ROLES),
    )
