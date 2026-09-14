"""Job lifecycle: assignment, start, complete, cancel.

Scoping:
  - JOBS_READ (owner, manager, dispatcher, analyst) sees every job in the tenant;
  - JOBS_WORK (technician) sees only the jobs assigned to them;
  - customers have no job access; they follow progress through their booking.

Writing is narrower than reading. JOBS_DISPATCH may assign and move any job
along; a technician may start and complete only their own; an analyst, who can
read everything, can change nothing.

Lock order is always booking, then job. Booking-side operations lock the booking
first and job-side operations look the booking id up and do the same, so two
requests that touch one appointment from either end serialise instead of
deadlocking.

Every status change goes through `services/state_machine.py`.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnExpressionArgument, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, lazyload
from sqlalchemy.orm.interfaces import LoaderOption

from serviceflow.auth.permissions import Permission as P
from serviceflow.auth.permissions import can
from serviceflow.core.errors import (
    InvalidRole,
    InvalidStateTransition,
    NotFound,
    ScheduleConflict,
)
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.services import audit, notifications, outbox, realtime
from serviceflow.services.conflicts import is_overlap_violation
from serviceflow.services.employees import find_employee_for_user, get_employee_for_user
from serviceflow.services.scheduling import AssignmentRequest, get_scheduling_policy
from serviceflow.services.search import like_pattern
from serviceflow.services.state_machine import transition_booking, transition_job

logger = logging.getLogger(__name__)


def job_options() -> tuple[LoaderOption, ...]:
    return (
        joinedload(Job.employee).joinedload(Employee.user),
        joinedload(Job.booking).joinedload(Booking.customer).joinedload(Customer.user),
        joinedload(Job.booking).joinedload(Booking.service),
    )


def employee_user_id(job: Job | None) -> uuid.UUID | None:
    """The assigned technician's user id, for addressing events. None when unassigned."""
    if job is None or job.employee is None:
        return None
    return job.employee.user_id


def _scoped_employee_id(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """None for tenant-wide readers, otherwise the caller's own employee id."""
    if can(roles, P.JOBS_READ, P.JOBS_DISPATCH):
        return None
    if can(roles, P.JOBS_WORK):
        return get_employee_for_user(db, organization_id, user_id).id
    raise InvalidRole()


def get_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Job:
    scope = _scoped_employee_id(db, organization_id, roles=roles, user_id=user_id)
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.organization_id == organization_id)
        .options(*job_options())
    )
    # A colleague's job reads exactly like one that does not exist.
    if job is None or (scope is not None and job.employee_id != scope):
        raise NotFound("We couldn't find that job.")
    return job


class JobAudience(enum.StrEnum):
    """How a caller reaches a job, which decides what of it they may see and change."""

    STAFF = "STAFF"  # a dispatcher, or the technician it is assigned to: may write
    READER = "READER"  # tenant-wide read access without write (an analyst)
    CUSTOMER = "CUSTOMER"  # the customer whose booking produced it


def resolve_job_for_viewer(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> tuple[Job, JobAudience]:
    """The single authorization boundary for a job's notes and photos.

    Everyone else - another technician, another customer, another tenant - gets
    the same 404, so a job id cannot be probed.
    """
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.organization_id == organization_id)
        .options(*job_options())
    )
    if job is None:
        raise NotFound("We couldn't find that job.")

    if can(roles, P.JOBS_DISPATCH):
        return job, JobAudience.STAFF

    if can(roles, P.JOBS_WORK):
        employee = find_employee_for_user(db, organization_id, user_id)
        if employee is not None and job.employee_id == employee.id:
            return job, JobAudience.STAFF

    if can(roles, P.JOBS_READ):
        return job, JobAudience.READER

    if can(roles, P.BOOKINGS_OWN):
        customer = db.scalar(
            select(Customer).where(
                Customer.organization_id == organization_id, Customer.user_id == user_id
            )
        )
        if customer is not None and job.booking.customer_id == customer.id:
            return job, JobAudience.CUSTOMER

    raise NotFound("We couldn't find that job.")


JOB_SORTS = frozenset({"scheduled_start", "created_at", "status"})


def list_jobs(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    pagination: PageParams,
    status: JobStatus | None = None,
    employee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    timeframe: str | None = None,
    q: str | None = None,
    sort: SortSpec | None = None,
) -> Page[Job]:
    filters: list[ColumnExpressionArgument[bool]] = [Job.organization_id == organization_id]

    scope = _scoped_employee_id(db, organization_id, roles=roles, user_id=user_id)
    if scope is not None:
        # A technician's filter can narrow their own work, never widen it.
        filters.append(Job.employee_id == scope)
    elif unassigned:
        filters.append(Job.employee_id.is_(None))
    elif employee_id is not None:
        filters.append(Job.employee_id == employee_id)

    if status is not None:
        filters.append(Job.status == status)
    if date_from is not None:
        filters.append(Job.scheduled_start >= date_from)
    if date_to is not None:
        filters.append(Job.scheduled_start < date_to)

    now = datetime.now(UTC)
    if timeframe == "upcoming":
        filters.append(Job.scheduled_end >= now)
    elif timeframe == "past":
        filters.append(Job.scheduled_end < now)

    if q:
        pattern = like_pattern(q)
        filters.append(
            Job.booking.has(
                or_(
                    Booking.customer.has(
                        Customer.user.has(
                            or_(
                                User.first_name.ilike(pattern),
                                User.last_name.ilike(pattern),
                                (User.first_name + " " + User.last_name).ilike(pattern),
                            )
                        )
                    ),
                    Booking.customer.has(Customer.address.ilike(pattern)),
                    Booking.service.has(Service.name.ilike(pattern)),
                )
            )
        )

    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Job)
            .where(*filters)
            .options(*job_options())
            .order_by(*_job_order(sort, timeframe))
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def _job_order(sort: SortSpec | None, timeframe: str | None) -> list[Any]:
    """Upcoming work reads soonest-first; history newest-first. Always ends unique."""
    if sort is None:
        ordered = (
            Job.scheduled_start.asc() if timeframe == "upcoming" else Job.scheduled_start.desc()
        )
        return [ordered, Job.id.asc()]
    columns = {
        "scheduled_start": Job.scheduled_start,
        "created_at": Job.created_at,
        "status": Job.status,
    }
    chosen = columns.get(sort.key, Job.scheduled_start)
    return [chosen.desc() if sort.descending else chosen.asc(), Job.id.asc()]


def jobs_in_range(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    employee_id: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
) -> list[Job]:
    """Jobs overlapping [start, end), for the schedule.

    Overlap rather than containment, so a job that begins before the window and
    runs into it still appears. Technicians are pinned to their own work.
    """
    filters: list[ColumnExpressionArgument[bool]] = [
        Job.organization_id == organization_id,
        Job.scheduled_start < end,
        Job.scheduled_end > start,
    ]

    if can(roles, P.SCHEDULE_READ, P.JOBS_READ):
        if employee_id is not None:
            filters.append(Job.employee_id == employee_id)
    elif can(roles, P.SCHEDULE_OWN, P.JOBS_WORK):
        filters.append(Job.employee_id == get_employee_for_user(db, organization_id, user_id).id)
    else:
        raise InvalidRole()

    if status is not None:
        filters.append(Job.status == status)
    if service_id is not None:
        filters.append(Job.booking.has(Booking.service_id == service_id))

    return list(
        db.scalars(
            select(Job)
            .where(*filters)
            .options(*job_options())
            .order_by(Job.scheduled_start.asc(), Job.id.asc())
        ).unique()
    )


# ----------------------------------------------------------------- locking


def lock_booking_and_job(
    db: Session, organization_id: uuid.UUID, *, job_id: uuid.UUID
) -> tuple[Booking, Job]:
    """Lock an appointment from its job end, in the canonical booking-then-job order."""
    booking_id = db.scalar(
        select(Job.booking_id).where(Job.id == job_id, Job.organization_id == organization_id)
    )
    if booking_id is None:
        raise NotFound("We couldn't find that job.")
    booking = db.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.organization_id == organization_id)
        # The relationships are lazy="joined", and PostgreSQL refuses FOR UPDATE
        # over an outer join, so lock queries load the row on its own. And
        # populate_existing, because the row may already sit in this session from
        # an unlocked read: without it the lock hands back that stale copy, and a
        # second confirmation racing the first would see "still unassigned".
        .options(lazyload("*"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.organization_id == organization_id)
        .options(lazyload("*"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if booking is None or job is None:  # pragma: no cover - read just above
        raise NotFound("We couldn't find that job.")
    return booking, job


def _require_writer(
    db: Session,
    organization_id: uuid.UUID,
    job: Job,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> None:
    """Dispatchers may change any job; a technician only one assigned to them."""
    if can(roles, P.JOBS_DISPATCH):
        return
    if can(roles, P.JOBS_WORK):
        employee = find_employee_for_user(db, organization_id, user_id)
        if employee is not None and job.employee_id == employee.id:
            return
        if not can(roles, P.JOBS_READ):
            raise NotFound("We couldn't find that job.")
    raise InvalidRole("Only the assigned technician or a dispatcher can update this job.")


def with_relations(db: Session, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Load the job with the relations a notification body or response needs."""
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.organization_id == organization_id)
        .options(*job_options())
        .execution_options(populate_existing=True)
    )
    if job is None:  # pragma: no cover - locked in this transaction
        raise NotFound("We couldn't find that job.")
    return job


def _reload(db: Session, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    db.expire_all()
    return with_relations(db, organization_id, job_id)


def _stage_job_event(db: Session, job: Job) -> None:
    outbox.stage_event(
        db,
        realtime.job_updated(
            organization_id=job.organization_id,
            job_id=job.id,
            customer_user_id=job.booking.customer.user_id,
            employee_user_id=employee_user_id(job),
        ),
    )


# ----------------------------------------------------------------- lifecycle


def start_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Job:
    _, job = lock_booking_and_job(db, organization_id, job_id=job_id)
    _require_writer(db, organization_id, job, roles=roles, user_id=user_id)
    transition_job(job, JobStatus.IN_PROGRESS)
    job.started_at = datetime.now(UTC)
    db.flush()
    loaded = with_relations(db, organization_id, job_id)
    notifications.job_started(db, loaded)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.JOB_STARTED,
        resource_type="job",
        resource_id=job_id,
        metadata={"service": loaded.booking.service.name},
    )
    _stage_job_event(db, loaded)
    db.commit()
    logger.info("job started", extra={"job_id": str(job_id)})
    return _reload(db, organization_id, job_id)


def complete_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    internal_notes: str | None = None,
) -> Job:
    _, job = lock_booking_and_job(db, organization_id, job_id=job_id)
    _require_writer(db, organization_id, job, roles=roles, user_id=user_id)
    transition_job(job, JobStatus.COMPLETED)
    job.completed_at = datetime.now(UTC)
    if internal_notes is not None:
        job.internal_notes = internal_notes
    db.flush()
    loaded = with_relations(db, organization_id, job_id)
    notifications.job_completed(db, loaded)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.JOB_COMPLETED,
        resource_type="job",
        resource_id=job_id,
        metadata={"service": loaded.booking.service.name},
    )
    _stage_job_event(db, loaded)
    db.commit()
    logger.info("job completed", extra={"job_id": str(job_id)})
    return _reload(db, organization_id, job_id)


def cancel_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> Job:
    """Cancel work that hasn't started, and the booking it belongs to.

    Callers are dispatchers (checked at the route). A job is never cancelled
    while its booking stays confirmed: the two move together or not at all.
    """
    booking, job = lock_booking_and_job(db, organization_id, job_id=job_id)
    transition_job(job, JobStatus.CANCELLED)
    if booking.is_open:
        transition_booking(booking, BookingStatus.CANCELLED)
    db.flush()
    loaded = with_relations(db, organization_id, job_id)
    notifications.booking_cancelled(db, loaded.booking, cancelled_by_customer=False)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.JOB_CANCELLED,
        resource_type="job",
        resource_id=job_id,
        metadata={"service": loaded.booking.service.name},
    )
    _stage_job_event(db, loaded)
    db.commit()
    logger.info("job cancelled", extra={"job_id": str(job_id)})
    return _reload(db, organization_id, job_id)


def assign_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    admin_notes: str | None = None,
    expect_unassigned: bool = False,
) -> Job:
    """Give a NEW job its technician, or move a SCHEDULED one to another.

    `expect_unassigned` is set when the caller is *confirming* a booking: two
    confirmations racing each other must produce one assignment and one refusal,
    not an assignment followed by a silent reassignment.

    The first assignment also confirms the booking, in the same transaction.
    Both paths run the scheduling policy - eligibility, working hours, the
    per-technician advisory lock and overlap detection - and the exclusion
    constraint stands behind all of it.
    """
    try:
        booking, job = lock_booking_and_job(db, organization_id, job_id=job_id)
        if job.status not in (JobStatus.NEW, JobStatus.SCHEDULED):
            raise InvalidStateTransition("Only work that hasn't started yet can be assigned.")
        if expect_unassigned and job.status is not JobStatus.NEW:
            raise InvalidStateTransition("This booking has already been confirmed.")
        if job.status is JobStatus.NEW:
            # Until someone is assigned, the booking is the source of truth for
            # when the work happens; the job takes its window at assignment.
            job.scheduled_start = booking.requested_start
            job.scheduled_end = booking.requested_end

        employee = db.scalar(
            select(Employee).where(
                Employee.id == employee_id, Employee.organization_id == organization_id
            )
        )
        if employee is None:
            raise NotFound("We couldn't find that employee.")
        service = db.scalar(
            select(Service).where(
                Service.id == booking.service_id, Service.organization_id == organization_id
            )
        )
        if service is None:  # pragma: no cover - composite FK guarantees this
            raise NotFound("We couldn't find that service.")

        get_scheduling_policy().check_assignment(
            db,
            AssignmentRequest(
                organization_id=organization_id,
                employee=employee,
                service=service,
                start=job.scheduled_start,
                end=job.scheduled_end,
                exclude_job_id=job.id,
            ),
        )

        first_assignment = job.status is JobStatus.NEW
        previous_employee_id = job.employee_id
        if first_assignment:
            transition_booking(booking, BookingStatus.CONFIRMED)
            transition_job(job, JobStatus.SCHEDULED)
        job.employee_id = employee.id
        if admin_notes is not None:
            booking.admin_notes = admin_notes
        db.flush()

        loaded = with_relations(db, organization_id, job_id)
        if first_assignment:
            notifications.booking_confirmed(
                db, loaded.booking, employee_name=employee.user.full_name
            )
            audit.record(
                db,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=AuditAction.BOOKING_CONFIRMED,
                resource_type="booking",
                resource_id=booking.id,
                metadata={
                    "employee": employee.user.full_name,
                    "scheduled_start": job.scheduled_start.isoformat(),
                },
            )
            audit.record(
                db,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=AuditAction.JOB_ASSIGNED,
                resource_type="job",
                resource_id=job.id,
                metadata={"employee": employee.user.full_name},
            )
        elif previous_employee_id != employee.id:
            previous = db.get(Employee, previous_employee_id) if previous_employee_id else None
            audit.record(
                db,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=AuditAction.JOB_REASSIGNED,
                resource_type="job",
                resource_id=job.id,
                metadata={
                    "from": previous.user.full_name if previous else None,
                    "to": employee.user.full_name,
                },
            )
        _stage_job_event(db, loaded)
        outbox.stage_event(
            db,
            realtime.booking_updated(
                organization_id=organization_id,
                booking_id=booking.id,
                customer_user_id=loaded.booking.customer.user_id,
                employee_user_id=employee.user_id,
            ),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_overlap_violation(exc):
            # Only reachable if a competing transaction committed between the
            # policy's check and this write; the constraint caught it.
            raise ScheduleConflict(
                "That technician was just booked for overlapping work."
                " Choose another employee or time."
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    logger.info("job assigned", extra={"job_id": str(job_id), "employee_id": str(employee_id)})
    return _reload(db, organization_id, job_id)


def update_notes(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    internal_notes: str | None,
) -> Job:
    _, job = lock_booking_and_job(db, organization_id, job_id=job_id)
    _require_writer(db, organization_id, job, roles=roles, user_id=user_id)
    job.internal_notes = internal_notes
    db.commit()
    return _reload(db, organization_id, job_id)


def employee_day_summary(
    db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID, *, day: datetime
) -> dict[str, int]:
    """Counts for a technician's dashboard header."""
    day_start = day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    rows = db.execute(
        select(Job.status, func.count())
        .where(
            Job.organization_id == organization_id,
            Job.employee_id == employee_id,
            Job.scheduled_start >= day_start,
            Job.scheduled_start < day_end,
        )
        .group_by(Job.status)
    ).all()

    counts = {status.value: 0 for status in JobStatus}
    for status, count in rows:
        counts[status.value] = count
    counts["TOTAL"] = sum(counts[status.value] for status in JobStatus)
    return counts
