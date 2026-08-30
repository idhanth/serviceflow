"""Appointment reminders (PRD 16).

A reminder goes out roughly 24 hours before the appointment. The beat runs every
five minutes and looks at a window around that mark, so a reminder is never
missed because a tick was late - but it also never fires twice, for two reasons:

  * an existing APPOINTMENT_REMINDER for the booking is checked before insert;
  * the whole sweep runs under one advisory lock, so two beats or two workers
    serialise rather than both finding the same booking unreminded.

That combination needs no schema change and no extra column.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import BookingStatus, JobStatus, NotificationType
from serviceflow.db.models.job import Job
from serviceflow.db.models.notification import Notification
from serviceflow.services import notifications

logger = logging.getLogger(__name__)

# A stable key, so every scheduler run contends for the same lock.
REMINDER_LOCK_KEY = 0x5E5217E  # "serviceflow reminders"


def _already_reminded(db: Session, booking: Booking) -> bool:
    """True if this booking has a reminder already.

    Matched on the payload's booking_id, which every notification carries.
    """
    existing = db.scalar(
        select(Notification.id).where(
            Notification.organization_id == booking.organization_id,
            Notification.type == NotificationType.APPOINTMENT_REMINDER,
            Notification.payload["booking_id"].astext == str(booking.id),
        )
    )
    return existing is not None


def due_bookings(
    db: Session, *, lead_hours: int, window_minutes: int, now: datetime | None = None
) -> list[Booking]:
    """Confirmed appointments falling inside the reminder window.

    Only CONFIRMED bookings whose job is still live qualify: a cancelled,
    rejected or already-completed appointment must not be reminded about.
    """
    now = now or datetime.now(UTC)
    target = now + timedelta(hours=lead_hours)
    window_start = target - timedelta(minutes=window_minutes)
    window_end = target + timedelta(minutes=window_minutes)

    return list(
        db.scalars(
            select(Booking)
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.requested_start >= window_start,
                Booking.requested_start <= window_end,
                # In the future regardless, so a late beat cannot remind about
                # something that has already happened.
                Booking.requested_start > now,
                Booking.job.has(Job.status.in_([JobStatus.ASSIGNED, JobStatus.IN_PROGRESS])),
            )
            .options(
                joinedload(Booking.customer).joinedload(Customer.user),
                joinedload(Booking.service),
                joinedload(Booking.vehicle),
            )
            .order_by(Booking.requested_start)
        ).unique()
    )


def create_due_reminders(
    db: Session,
    *,
    lead_hours: int,
    window_minutes: int,
    now: datetime | None = None,
) -> int:
    """Stage reminder notifications for everything due. Commits once at the end.

    The advisory lock is transaction-scoped: it is released by the commit or
    rollback below, and it is what makes concurrent scheduler runs safe.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": REMINDER_LOCK_KEY})

    created = 0
    for booking in due_bookings(db, lead_hours=lead_hours, window_minutes=window_minutes, now=now):
        if _already_reminded(db, booking):
            continue
        notifications.appointment_reminder(db, booking)
        created += 1

    db.commit()
    if created:
        logger.info("created appointment reminders", extra={"count": created})
    return created
