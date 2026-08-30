"""In-app notifications (PRD 16).

Two rules shape this module.

**Notifications are written inside the transaction of the event they describe.**
`enqueue` adds rows to the caller's session and never commits. If the booking
confirmation that triggered it rolls back, so does the notification - a customer
can never be told about something that did not happen.

**Phase 6 is a seam, not a rewrite.** `enqueue` already takes a list of channels
and writes one row per channel with `status = PENDING`; phase 5 asks for IN_APP
only. Adding email means passing `EMAIL` too and giving a worker the job of
moving those rows to SENT/FAILED - `sent_at` and `failed_at` already exist. No
booking or job logic changes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from serviceflow.core.errors import NotFound
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import (
    MembershipStatus,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    Role,
)
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS: tuple[NotificationChannel, ...] = (NotificationChannel.IN_APP,)


# --------------------------------------------------------------- writing


def enqueue(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    type: NotificationType,
    subject: str,
    body: str,
    payload: dict[str, Any] | None = None,
    channels: Sequence[NotificationChannel] = DEFAULT_CHANNELS,
) -> list[Notification]:
    """Stage notifications on the caller's session. Does not commit, by design."""
    created: list[Notification] = []
    for channel in channels:
        notification = Notification(
            organization_id=organization_id,
            user_id=user_id,
            type=type,
            channel=channel,
            status=NotificationStatus.PENDING,
            subject=subject,
            body=body,
            payload=payload,
        )
        db.add(notification)
        created.append(notification)
    return created


def _admin_user_ids(db: Session, organization_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(OrganizationMembership.user_id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == Role.ADMIN,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
    )


def _when(db: Session, organization_id: uuid.UUID, moment: datetime) -> str:
    """Format an instant in the shop's timezone, which is what people booked in."""
    organization = db.get(Organization, organization_id)
    tz = ZoneInfo(organization.timezone if organization else "UTC")
    local = moment.astimezone(tz)
    return local.strftime("%a %-d %b at %-I:%M%p").replace("AM", "am").replace("PM", "pm")


def _booking_payload(booking: Booking) -> dict[str, Any]:
    return {"booking_id": str(booking.id), "job_id": str(booking.job.id) if booking.job else None}


# --------------------------------------------------------------- events


def booking_created(db: Session, booking: Booking) -> None:
    """Admins have something to review; the customer gets an acknowledgement."""
    when = _when(db, booking.organization_id, booking.requested_start)
    service = booking.service.name
    customer_name = booking.customer.user.full_name

    for admin_id in _admin_user_ids(db, booking.organization_id):
        enqueue(
            db,
            organization_id=booking.organization_id,
            user_id=admin_id,
            type=NotificationType.BOOKING_CREATED,
            subject=f"New booking request from {customer_name}",
            body=f"{service} requested for {when}. Review it to assign a technician.",
            payload=_booking_payload(booking),
        )

    enqueue(
        db,
        organization_id=booking.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.BOOKING_CREATED,
        subject="We received your booking request",
        body=f"Your {service} for {when} is waiting to be confirmed.",
        payload=_booking_payload(booking),
    )


def booking_confirmed(db: Session, booking: Booking, *, employee_name: str) -> None:
    when = _when(db, booking.organization_id, booking.requested_start)
    enqueue(
        db,
        organization_id=booking.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.BOOKING_CONFIRMED,
        subject=f"Your {booking.service.name} is confirmed",
        body=f"{employee_name} will take care of it on {when}.",
        payload=_booking_payload(booking),
    )


def booking_rejected(db: Session, booking: Booking) -> None:
    when = _when(db, booking.organization_id, booking.requested_start)
    enqueue(
        db,
        organization_id=booking.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.BOOKING_REJECTED,
        subject=f"We couldn't take your {booking.service.name} booking",
        body=f"Your request for {when} wasn't accepted. Please try another time.",
        payload=_booking_payload(booking),
    )


def booking_rescheduled(db: Session, booking: Booking) -> None:
    when = _when(db, booking.organization_id, booking.requested_start)
    enqueue(
        db,
        organization_id=booking.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.BOOKING_RESCHEDULED,
        subject=f"Your {booking.service.name} has moved",
        body=f"It's now scheduled for {when}.",
        payload=_booking_payload(booking),
    )
    if booking.job is not None:
        enqueue(
            db,
            organization_id=booking.organization_id,
            user_id=booking.job.employee.user_id,
            type=NotificationType.BOOKING_RESCHEDULED,
            subject=f"{booking.service.name} moved to {when}",
            body=f"{booking.customer.user.full_name}'s appointment was rescheduled.",
            payload=_booking_payload(booking),
        )


def booking_cancelled(db: Session, booking: Booking, *, cancelled_by_customer: bool) -> None:
    """Whoever did not do the cancelling is the one who needs telling."""
    when = _when(db, booking.organization_id, booking.requested_start)
    service = booking.service.name

    if cancelled_by_customer:
        for admin_id in _admin_user_ids(db, booking.organization_id):
            enqueue(
                db,
                organization_id=booking.organization_id,
                user_id=admin_id,
                type=NotificationType.BOOKING_CANCELLED,
                subject=f"{booking.customer.user.full_name} cancelled a booking",
                body=f"{service} on {when} was cancelled by the customer.",
                payload=_booking_payload(booking),
            )
    else:
        enqueue(
            db,
            organization_id=booking.organization_id,
            user_id=booking.customer.user_id,
            type=NotificationType.BOOKING_CANCELLED,
            subject=f"Your {service} booking was cancelled",
            body=f"The appointment on {when} is no longer scheduled.",
            payload=_booking_payload(booking),
        )

    if booking.job is not None:
        enqueue(
            db,
            organization_id=booking.organization_id,
            user_id=booking.job.employee.user_id,
            type=NotificationType.BOOKING_CANCELLED,
            subject=f"{service} on {when} was cancelled",
            body="It has been removed from your schedule.",
            payload=_booking_payload(booking),
        )


def job_started(db: Session, job: Job) -> None:
    booking = job.booking
    enqueue(
        db,
        organization_id=job.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.JOB_STARTED,
        subject=f"Work has started on your {booking.vehicle.display_name}",
        body=f"{job.employee.user.full_name} has begun the {booking.service.name}.",
        payload={"booking_id": str(booking.id), "job_id": str(job.id)},
    )


def job_completed(db: Session, job: Job) -> None:
    booking = job.booking
    enqueue(
        db,
        organization_id=job.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.JOB_COMPLETED,
        subject=f"Your {booking.service.name} is finished",
        body=(
            f"{booking.vehicle.display_name} is ready. "
            "Open the booking to see photos and notes from the visit."
        ),
        payload={"booking_id": str(booking.id), "job_id": str(job.id)},
    )


def appointment_reminder(db: Session, booking: Booking) -> None:
    """Built now, scheduled in phase 6 by the periodic reminder task."""
    when = _when(db, booking.organization_id, booking.requested_start)
    enqueue(
        db,
        organization_id=booking.organization_id,
        user_id=booking.customer.user_id,
        type=NotificationType.APPOINTMENT_REMINDER,
        subject=f"Reminder: {booking.service.name} on {when}",
        body=f"We'll see you and your {booking.vehicle.display_name} then.",
        payload=_booking_payload(booking),
    )


# --------------------------------------------------------------- reading


def list_notifications(
    db: Session,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    pagination: PageParams,
    unread_only: bool = False,
) -> Page[Notification]:
    """Only ever the caller's own rows, in the active organization."""
    filters = [
        Notification.organization_id == organization_id,
        Notification.user_id == user_id,
        Notification.channel == NotificationChannel.IN_APP,
    ]
    if unread_only:
        filters.append(Notification.status == NotificationStatus.PENDING)

    total = db.scalar(select(func.count()).select_from(Notification).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
    )
    return Page(items=items, total=total)


def unread_count(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
                Notification.channel == NotificationChannel.IN_APP,
                Notification.status == NotificationStatus.PENDING,
            )
        )
        or 0
    )


def mark_read(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == organization_id,
            # Scoped to the caller, so another user's id reads as not-found.
            Notification.user_id == user_id,
        )
    )
    if notification is None:
        raise NotFound("We couldn't find that notification.")

    if notification.status is NotificationStatus.PENDING:
        notification.status = NotificationStatus.READ
        notification.sent_at = notification.sent_at or datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_read(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    result = db.execute(
        update(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.status == NotificationStatus.PENDING,
        )
        .values(status=NotificationStatus.READ, sent_at=now)
    )
    db.commit()
    return int(cast("CursorResult[Any]", result).rowcount or 0)
