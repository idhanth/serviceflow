"""What happens *after* a business transaction commits.

Phase 5 established that notifications are staged inside the caller's
transaction and never committed independently. Phase 6 keeps that and adds the
other half: the side effects that must not happen until the commit succeeds.

    stage_email(...)  /  stage_event(...)      during the transaction
                    |
                 COMMIT
                    |
        after_commit listener fires            queue Celery, publish to Redis

Nothing here can fail the request. A booking that committed has happened; if the
broker or Redis is unreachable the email stays PENDING in the outbox for the
sweep, and the client's next refetch shows the correct state anyway.

Business services never call Celery or Redis directly - they stage, and this
module decides when.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from serviceflow.core.context import current_context
from serviceflow.services.realtime import RealtimeEvent, publish

logger = logging.getLogger(__name__)

_EMAIL_KEY = "_sf_pending_emails"
_EVENT_KEY = "_sf_pending_events"


def stage_email(db: Session, notification_id: uuid.UUID) -> None:
    """Queue this notification for dispatch once the transaction commits.

    The request's correlation fields are captured now and handed to the worker,
    so a delivery log line can be traced back to the request that caused it.
    """
    db.info.setdefault(_EMAIL_KEY, []).append((notification_id, current_context()))


def stage_event(db: Session, realtime_event: RealtimeEvent) -> None:
    """Broadcast this event once the transaction commits."""
    db.info.setdefault(_EVENT_KEY, []).append(realtime_event)


def _drain(session: Session, key: str) -> list[Any]:
    staged = session.info.pop(key, [])
    return list(staged)


@event.listens_for(Session, "after_commit")
def _flush_outbox(session: Session) -> None:
    """Fire staged side effects. Never raises into the caller."""
    for notification_id, context in _drain(session, _EMAIL_KEY):
        try:
            # Imported here: the worker imports this module, and importing tasks
            # at module scope would make that circular.
            from serviceflow.worker.tasks import dispatch_email

            dispatch_email.delay(str(notification_id), context=context)
        except Exception:
            logger.warning(
                "could not queue email dispatch; left for the sweep",
                extra={"notification_id": str(notification_id)},
            )

    for realtime_event in _drain(session, _EVENT_KEY):
        publish(realtime_event)


@event.listens_for(Session, "after_rollback")
def _discard_outbox(session: Session) -> None:
    """A rolled-back transaction announces nothing."""
    _drain(session, _EMAIL_KEY)
    _drain(session, _EVENT_KEY)
