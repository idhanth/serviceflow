"""Job lifecycle: assignment, start, complete, cancel (PRD 12).

Scoping (PRD 6):
  - an employee sees and acts on only the jobs assigned to them;
  - an admin sees and acts on every job in the active organization.

Every status change goes through `services/state_machine.py`, so an invalid move
raises 409 INVALID_STATE_TRANSITION from one place.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, lazyload
from sqlalchemy.orm.interfaces import LoaderOption

from serviceflow.core.errors import InvalidStateTransition, NotFound, ScheduleConflict
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.services.conflicts import is_overlap_violation
from serviceflow.services.employees import get_employee_for_user
from serviceflow.services.scheduling import AssignmentRequest, get_scheduling_policy
from serviceflow.services.state_machine import transition_job

logger = logging.getLogger(__name__)


def _job_options() -> tuple[LoaderOption, ...]:
    return (
        joinedload(Job.employee).joinedload(Employee.user),
        joinedload(Job.booking).joinedload(Booking.customer).joinedload(Customer.user),
        joinedload(Job.booking).joinedload(Booking.vehicle),
        joinedload(Job.booking).joinedload(Booking.service),
    )


def _scoped_employee_id(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """None for an admin, otherwise the caller's own employee id."""
    if Role.ADMIN in roles:
        return None
    return get_employee_for_user(db, organization_id, user_id).id


def get_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    for_update: bool = False,
) -> Job:
    statement = select(Job).where(Job.id == job_id, Job.organization_id == organization_id)
    if for_update:
        # See load_booking: FOR UPDATE cannot span the eager-loaded outer joins.
        statement = statement.options(lazyload("*")).with_for_update()
    else:
        statement = statement.options(*_job_options())

    job = db.scalar(statement)
    if job is None:
        raise NotFound("We couldn't find that job.")

    scope = _scoped_employee_id(db, organization_id, roles=roles, user_id=user_id)
    # A colleague's job reads exactly like one that does not exist.
    if scope is not None and job.employee_id != scope:
        raise NotFound("We couldn't find that job.")
    return job


def list_jobs(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    pagination: PageParams,
    status: JobStatus | None = None,
    employee_id: uuid.UUID | None = None,
    on_date: datetime | None = None,
) -> Page[Job]:
    filters = [Job.organization_id == organization_id]

    scope = _scoped_employee_id(db, organization_id, roles=roles, user_id=user_id)
    if scope is not None:
        filters.append(Job.employee_id == scope)
    elif employee_id is not None:
        filters.append(Job.employee_id == employee_id)

    if status is not None:
        filters.append(Job.status == status)
    if on_date is not None:
        day_start = on_date.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        filters.extend(
            [
                Job.scheduled_start >= day_start,
                Job.scheduled_start < day_start + timedelta(days=1),
            ]
        )

    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Job)
            .where(*filters)
            .options(*_job_options())
            .order_by(Job.scheduled_start.asc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


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
    """Jobs overlapping [start, end), for the calendar.

    Overlap rather than containment, so a job that begins before the window and
    runs into it still appears. Employees are pinned to their own work; an
    employee_id filter cannot widen that.
    """
    filters = [
        Job.organization_id == organization_id,
        Job.scheduled_start < end,
        Job.scheduled_end > start,
    ]

    scope = _scoped_employee_id(db, organization_id, roles=roles, user_id=user_id)
    if scope is not None:
        filters.append(Job.employee_id == scope)
    elif employee_id is not None:
        filters.append(Job.employee_id == employee_id)

    if status is not None:
        filters.append(Job.status == status)
    if service_id is not None:
        filters.append(Job.booking.has(Booking.service_id == service_id))

    return list(
        db.scalars(
            select(Job)
            .where(*filters)
            .options(*_job_options())
            .order_by(Job.scheduled_start.asc(), Job.id.asc())
        ).unique()
    )


def _reload(db: Session, organization_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    db.expire_all()
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.organization_id == organization_id)
        .options(*_job_options())
    )
    if job is None:  # pragma: no cover - just written in this transaction
        raise NotFound("We couldn't find that job.")
    return job


def start_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Job:
    job = get_job(db, organization_id, job_id, roles=roles, user_id=user_id, for_update=True)
    transition_job(job, JobStatus.IN_PROGRESS)
    job.started_at = datetime.now(UTC)
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
    job = get_job(db, organization_id, job_id, roles=roles, user_id=user_id, for_update=True)
    transition_job(job, JobStatus.COMPLETED)
    job.completed_at = datetime.now(UTC)
    if internal_notes is not None:
        job.internal_notes = internal_notes
    db.commit()
    logger.info("job completed", extra={"job_id": str(job_id)})
    return _reload(db, organization_id, job_id)


def cancel_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Job:
    """Admin-only cancellation of assigned work. Started work cannot be cancelled."""
    job = get_job(db, organization_id, job_id, roles=roles, user_id=user_id, for_update=True)
    transition_job(job, JobStatus.CANCELLED)
    db.commit()
    logger.info("job cancelled", extra={"job_id": str(job_id)})
    return _reload(db, organization_id, job_id)


def reassign_job(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> Job:
    """Move assigned work to a different employee.

    Runs the same scheduling policy as confirmation, so phase 4's availability and
    overlap rules apply to reassignment automatically.
    """
    job = get_job(db, organization_id, job_id, roles=roles, user_id=user_id)
    if job.status is not JobStatus.ASSIGNED:
        raise InvalidStateTransition("Only work that hasn't started yet can be reassigned.")

    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.organization_id == organization_id
        )
    )
    if employee is None:
        raise NotFound("We couldn't find that employee.")

    service = db.get(Service, job.booking.service_id)
    if service is None:  # pragma: no cover - FK guarantees this
        raise NotFound("We couldn't find that service.")

    try:
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
        job.employee_id = employee.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_overlap_violation(exc):
            raise ScheduleConflict(
                f"{employee.user.full_name} already has overlapping work at that time."
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    logger.info("job reassigned", extra={"job_id": str(job_id), "employee_id": str(employee_id)})
    return _reload(db, organization_id, job_id)


def employee_day_summary(
    db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID, *, day: datetime
) -> dict[str, int]:
    """Counts for the employee dashboard header."""
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
