"""Background tasks.

Nothing here is called from a request path. The API commits its transaction and
queues a task; if queuing fails the row is still in the outbox and the sweep
picks it up. No request ever waits on an email provider.
"""

from __future__ import annotations

import logging
import uuid

from celery.exceptions import MaxRetriesExceededError

from serviceflow.core.config import get_settings
from serviceflow.db.session import session_scope
from serviceflow.services import delivery, reminders
from serviceflow.services.email import EmailDeliveryError
from serviceflow.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="serviceflow.dispatch_email",
    bind=True,
    # Bounded exponential backoff with jitter, so a provider blip does not turn
    # into a synchronised retry storm. Retries are requested explicitly below
    # rather than with autoretry_for, because a permanent rejection has to be
    # told apart from a transient one.
    retry_backoff=5,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def dispatch_email(self, notification_id: str) -> str:  # type: ignore[no-untyped-def]
    """Send one EMAIL notification.

    The row is claimed with SELECT ... FOR UPDATE SKIP LOCKED and held for the
    provider call, so two workers never send the same message at once. Anything
    already SENT or FAILED is a no-op, which makes redelivery of this task safe.
    """
    identifier = uuid.UUID(notification_id)

    with session_scope() as db:
        notification = delivery.claim_for_send(db, identifier)
        if notification is None:
            # Already sent, already failed, or another worker holds it.
            logger.info("email dispatch skipped", extra={"notification_id": notification_id})
            return "skipped"

        try:
            provider_id = delivery.deliver(db, notification)
        except delivery.PermanentDeliveryFailure as exc:
            delivery.mark_failed(db, notification, str(exc))
            return "failed"
        except EmailDeliveryError as exc:
            # Release the row before backing off, so the sweep and other workers
            # are not blocked behind this transaction.
            db.rollback()
            try:
                raise self.retry(exc=exc) from exc
            except MaxRetriesExceededError:
                with session_scope() as final_db:
                    stuck = delivery.claim_for_send(final_db, identifier)
                    if stuck is not None:
                        delivery.mark_failed(final_db, stuck, "retries exhausted")
                return "failed"

        delivery.mark_sent(db, notification)
        logger.info(
            "email sent",
            extra={
                "notification_id": notification_id,
                "notification_type": notification.type.value,
                "provider_message_id": provider_id,
            },
        )
        return "sent"


@celery_app.task(name="serviceflow.sweep_pending_emails", acks_late=True)  # type: ignore[untyped-decorator]
def sweep_pending_emails() -> int:
    """Re-queue EMAIL rows that were committed but never dispatched.

    This is what makes a broker outage immediately after the business commit
    recoverable rather than a lost email.
    """
    with session_scope() as db:
        stranded = delivery.stranded_pending_ids(db)

    for notification_id in stranded:
        dispatch_email.delay(str(notification_id))

    if stranded:
        logger.info("swept stranded emails", extra={"count": len(stranded)})
    return len(stranded)


@celery_app.task(name="serviceflow.queue_appointment_reminders", acks_late=True)  # type: ignore[untyped-decorator]
def queue_appointment_reminders() -> int:
    """Create reminder notifications for appointments coming up.

    Idempotent and serialised, so running it twice - or two beats overlapping -
    creates nothing extra.
    """
    settings = get_settings()
    with session_scope() as db:
        created = reminders.create_due_reminders(
            db,
            lead_hours=settings.reminder_lead_hours,
            window_minutes=settings.reminder_window_minutes,
        )
    if created:
        logger.info("queued appointment reminders", extra={"count": created})
    return created
