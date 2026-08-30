"""Backfills an audit trail for the seeded history (PRD 35, 49).

The rest of the seed writes rows directly rather than calling the services, so
nothing has recorded who did what - and an Activity page that is empty on a
freshly seeded demo tells the wrong story about the feature. This reconstructs
the trail the same actions would have left: the customer requested it, an admin
confirmed and assigned it, the assigned employee started and finished it.

Timestamps are derived from each booking, so the feed reads as history rather
than as 700 rows created the moment the seed ran.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import AuditAction, BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User


def _admin_user_id(db: Session, org: Organization) -> uuid.UUID | None:
    return db.scalar(
        select(User.id)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.role == Role.ADMIN,
        )
        .order_by(User.created_at)
        .limit(1)
    )


def seed_audit_trail(db: Session, org: Organization, rng: random.Random) -> int:
    """Write one entry per lifecycle step of every seeded booking."""
    if db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.organization_id == org.id)
    ):
        return 0

    admin_id = _admin_user_id(db, org)
    # Much of the seeded workload is in the future. A request for an appointment
    # three weeks out was still made in the past, so every entry is clamped to
    # now: an audit trail that records things before they happened is not one.
    now = datetime.now(UTC)
    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.organization_id == org.id)
            .order_by(Booking.requested_start, Booking.created_at)
            .options(
                joinedload(Booking.customer),
                joinedload(Booking.service),
                joinedload(Booking.vehicle),
                joinedload(Booking.job).joinedload(Job.employee),
            )
        ).unique()
    )

    entries: list[AuditLog] = []

    def add(
        action: AuditAction,
        *,
        actor_id: uuid.UUID | None,
        resource_type: str,
        resource_id: uuid.UUID,
        at: datetime,
        metadata: dict[str, object] | None = None,
    ) -> None:
        entries.append(
            AuditLog(
                organization_id=org.id,
                actor_user_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_=metadata,
                created_at=min(at, now),
            )
        )

    for booking in bookings:
        customer_user_id = booking.customer.user_id
        vehicle = f"{booking.vehicle.year} {booking.vehicle.make} {booking.vehicle.model}"
        # Requests come in a day or two before the appointment.
        requested_at = min(
            booking.requested_start - timedelta(days=rng.randint(1, 4), hours=rng.randint(0, 9)),
            now - timedelta(hours=rng.randint(1, 72)),
        )
        add(
            AuditAction.BOOKING_CREATED,
            actor_id=customer_user_id,
            resource_type="booking",
            resource_id=booking.id,
            at=requested_at,
            metadata={
                "service": booking.service.name,
                "vehicle": vehicle,
                "requested_start": booking.requested_start.isoformat(),
            },
        )

        decided_at = requested_at + timedelta(hours=rng.randint(1, 12))
        if booking.status is BookingStatus.REJECTED:
            add(
                AuditAction.BOOKING_REJECTED,
                actor_id=admin_id,
                resource_type="booking",
                resource_id=booking.id,
                at=decided_at,
                metadata={"service": booking.service.name},
            )
            continue

        if booking.status is BookingStatus.PENDING:
            continue

        job = booking.job
        if job is not None:
            add(
                AuditAction.BOOKING_CONFIRMED,
                actor_id=admin_id,
                resource_type="booking",
                resource_id=booking.id,
                at=decided_at,
                metadata={
                    "service": booking.service.name,
                    "employee": job.employee.user.full_name if job.employee else None,
                },
            )
            add(
                AuditAction.JOB_ASSIGNED,
                actor_id=admin_id,
                resource_type="job",
                resource_id=job.id,
                at=decided_at,
                metadata={
                    "employee": job.employee.user.full_name if job.employee else None,
                    "scheduled_start": job.scheduled_start.isoformat(),
                },
            )
            employee_user_id = job.employee.user_id if job.employee else None
            if job.started_at:
                add(
                    AuditAction.JOB_STARTED,
                    actor_id=employee_user_id,
                    resource_type="job",
                    resource_id=job.id,
                    at=job.started_at,
                    metadata={"service": booking.service.name},
                )
            if job.status is JobStatus.COMPLETED and job.completed_at:
                add(
                    AuditAction.JOB_COMPLETED,
                    actor_id=employee_user_id,
                    resource_type="job",
                    resource_id=job.id,
                    at=job.completed_at,
                    metadata={"service": booking.service.name, "vehicle": vehicle},
                )

        if booking.status is BookingStatus.CANCELLED:
            cancelled_at = min(
                booking.requested_start - timedelta(hours=rng.randint(2, 30)),
                booking.requested_start,
            )
            by_customer = rng.random() < 0.6
            add(
                AuditAction.BOOKING_CANCELLED,
                actor_id=customer_user_id if by_customer else admin_id,
                resource_type="booking",
                resource_id=booking.id,
                at=max(cancelled_at, decided_at),
                metadata={"service": booking.service.name, "by_customer": by_customer},
            )

    db.add_all(entries)
    db.flush()
    return len(entries)
