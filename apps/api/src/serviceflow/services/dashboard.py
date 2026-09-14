"""The operations dashboard.

Every figure here answers a question a dispatcher or owner acts on during the
day: what is booked today, who is working, what is running late, and what
still has nobody assigned. Nothing is decorative, and every number is one
aggregate query rather than a list counted in Python.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.schemas.admin import CustomerBrief, DashboardCounts, DashboardRead
from serviceflow.schemas.schedule import ScheduleEntry
from serviceflow.services.jobs import job_options
from serviceflow.services.schedule_view import working_days
from serviceflow.services.scheduling import organization_timezone

# A scheduled job not started this long after its start time is running late.
LATE_AFTER = dt.timedelta(minutes=15)
# Unassigned work starting within this window needs a technician soon.
ATTENTION_HORIZON = dt.timedelta(hours=48)
LIST_LIMIT = 6


def _count(db: Session, statement: object) -> int:
    return int(db.scalar(statement) or 0)  # type: ignore[call-overload]


def build_dashboard(
    db: Session, organization_id: uuid.UUID, *, now: dt.datetime | None = None
) -> DashboardRead:
    now = now or dt.datetime.now(dt.UTC)
    timezone = organization_timezone(db, organization_id)
    tz = ZoneInfo(timezone)
    today = now.astimezone(tz).date()
    day_start = dt.datetime.combine(today, dt.time.min, tzinfo=tz)
    day_end = day_start + dt.timedelta(days=1)

    job_count = select(func.count()).select_from(Job).where(Job.organization_id == organization_id)

    bookings_today = _count(
        db,
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.organization_id == organization_id,
            Booking.requested_start >= day_start,
            Booking.requested_start < day_end,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        ),
    )
    in_progress = _count(db, job_count.where(Job.status == JobStatus.IN_PROGRESS))
    completed_today = _count(
        db,
        job_count.where(
            Job.status == JobStatus.COMPLETED,
            Job.completed_at >= day_start,
            Job.completed_at < day_end,
        ),
    )
    remaining_today = _count(
        db,
        job_count.where(
            Job.status.in_([JobStatus.NEW, JobStatus.SCHEDULED]),
            Job.scheduled_start >= now,
            Job.scheduled_start < day_end,
        ),
    )
    unassigned = _count(
        db, job_count.where(Job.status == JobStatus.NEW, Job.scheduled_start >= now)
    )
    pending = _count(
        db,
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.organization_id == organization_id,
            Booking.status == BookingStatus.PENDING,
            Booking.requested_start >= now,
        ),
    )

    technician_ids = list(
        db.scalars(
            select(Employee.id).where(
                Employee.organization_id == organization_id, Employee.active.is_(True)
            )
        )
    )
    hours = working_days(db, organization_id, technician_ids, [today])
    working = sum(1 for days in hours.values() if days and days[0].windows)

    def entries(statement: object) -> list[ScheduleEntry]:
        rows = db.scalars(statement).unique()  # type: ignore[call-overload]
        return [ScheduleEntry.from_model(job) for job in rows]

    base = select(Job).where(Job.organization_id == organization_id).options(*job_options())
    needs_attention = entries(
        base.where(
            Job.status == JobStatus.NEW,
            Job.scheduled_start >= now,
            Job.scheduled_start < now + ATTENTION_HORIZON,
        )
        .order_by(Job.scheduled_start, Job.id)
        .limit(LIST_LIMIT)
    )
    overdue = entries(
        base.where(
            Job.status == JobStatus.SCHEDULED,
            Job.scheduled_start < now - LATE_AFTER,
            Job.scheduled_start >= day_start,
        )
        .order_by(Job.scheduled_start, Job.id)
        .limit(LIST_LIMIT)
    )
    upcoming = entries(
        base.where(Job.status == JobStatus.SCHEDULED, Job.scheduled_start >= now)
        .order_by(Job.scheduled_start, Job.id)
        .limit(8)
    )

    recent = db.scalars(
        select(Customer)
        .where(Customer.organization_id == organization_id, Customer.archived_at.is_(None))
        .order_by(Customer.created_at.desc(), Customer.id)
        .limit(5)
    ).unique()

    return DashboardRead(
        timezone=timezone,
        date=today,
        counts=DashboardCounts(
            bookings_today=bookings_today,
            jobs_in_progress=in_progress,
            jobs_completed_today=completed_today,
            jobs_remaining_today=remaining_today,
            technicians_working_today=working,
            technicians_total=len(technician_ids),
            unassigned_jobs=unassigned,
            pending_bookings=pending,
        ),
        needs_attention=needs_attention,
        overdue=overdue,
        upcoming=upcoming,
        recent_customers=[
            CustomerBrief(
                id=customer.id,
                full_name=customer.user.full_name,
                address=customer.address,
                created_at=customer.created_at,
            )
            for customer in recent
        ],
    )
