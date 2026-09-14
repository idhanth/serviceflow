"""Email delivery against the notification outbox.

The `notifications` table is the durable record. Phase 5 already staged rows
inside the business transaction; phase 6 treats the committed EMAIL rows as an
outbox:

    business transaction -> write IN_APP + EMAIL rows -> COMMIT
                                                          |
                        Celery dispatch (queued after commit)
                                                          |
                        periodic sweep picks up anything missed

Nothing external happens before the commit, so a rolled-back booking can never
produce an email. If the broker is down at commit time the row simply stays
PENDING and the sweep finds it.

**Delivery is at-least-once, not exactly-once.** The row is locked while the
provider call is in flight, so two workers never send the same message
concurrently. But if a worker dies after the provider accepts and before the
COMMIT that marks it SENT, the row stays PENDING and the message is sent again.
Closing that window would need a provider with idempotency keys and a two-phase
handshake; claiming exactly-once here would be false.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from serviceflow.core.config import get_settings
from serviceflow.db.models.enums import NotificationChannel, NotificationStatus
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User
from serviceflow.db.tenancy import allow_cross_tenant
from serviceflow.services.email import EmailDeliveryError, get_email_provider
from serviceflow.services.email.render import render

logger = logging.getLogger(__name__)

# How long a row may sit PENDING before the sweep considers it stranded. Long
# enough that the normal post-commit dispatch has had its chance.
STRANDED_AFTER_SECONDS = 60
SWEEP_BATCH = 50


class PermanentDeliveryFailure(Exception):
    """The provider will never accept this message; do not retry."""


def claim_for_send(db: Session, notification_id: uuid.UUID) -> Notification | None:
    """Lock one pending EMAIL row for this transaction, or return None.

    SKIP LOCKED means a second worker holding the same task moves on rather than
    waiting, so the message is never sent twice concurrently.
    """
    allow_cross_tenant(db)  # the outbox spans every tenant
    return db.scalar(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.channel == NotificationChannel.EMAIL,
            Notification.status == NotificationStatus.PENDING,
        )
        # Notification.user is lazy="joined", and PostgreSQL refuses FOR UPDATE
        # over an outer join - the same constraint the booking and job locks hit.
        .options(lazyload("*"))
        .with_for_update(skip_locked=True)
    )


def deliver(db: Session, notification: Notification) -> str:
    """Send one claimed notification. Caller owns the transaction."""
    user = db.get(User, notification.user_id)
    organization = db.get(Organization, notification.organization_id)
    if user is None or organization is None:  # pragma: no cover - FKs guarantee both
        raise PermanentDeliveryFailure("The recipient no longer exists.")

    settings = get_settings()
    message = render(
        notification,
        organization=organization,
        recipient_email=user.email,
        recipient_name=user.full_name,
        app_url=settings.cors_origins[0] if settings.cors_origins else "http://localhost:3000",
    )

    provider = get_email_provider()
    try:
        provider_id = provider.send(message)
    except EmailDeliveryError as exc:
        if exc.permanent:
            raise PermanentDeliveryFailure(str(exc)) from exc
        raise

    return provider_id


def mark_sent(db: Session, notification: Notification) -> None:
    notification.status = NotificationStatus.SENT
    notification.sent_at = datetime.now(UTC)
    notification.failed_at = None


def mark_failed(db: Session, notification: Notification, reason: str) -> None:
    """Terminal: retries are exhausted, or the provider rejected it outright."""
    notification.status = NotificationStatus.FAILED
    notification.failed_at = datetime.now(UTC)
    logger.warning(
        "email delivery failed permanently",
        extra={
            "notification_id": str(notification.id),
            "notification_type": notification.type.value,
            "reason": reason,
        },
    )


def stranded_pending_ids(db: Session, *, limit: int = SWEEP_BATCH) -> list[uuid.UUID]:
    """EMAIL rows committed a while ago that are still waiting.

    Either their dispatch was never queued (broker outage at commit time) or the
    worker holding them was lost.
    """
    allow_cross_tenant(db)  # the outbox spans every tenant
    cutoff = datetime.now(UTC) - timedelta(seconds=STRANDED_AFTER_SECONDS)
    return list(
        db.scalars(
            select(Notification.id)
            .where(
                Notification.channel == NotificationChannel.EMAIL,
                Notification.status == NotificationStatus.PENDING,
                Notification.created_at <= cutoff,
            )
            .order_by(Notification.created_at)
            .limit(limit)
        )
    )
