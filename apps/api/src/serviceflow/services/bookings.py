"""Booking workflow: create, assign, reject, cancel, reschedule.

The flow a booking follows:

    select customer -> service -> technician (optional) -> time
      -> tenant membership of every referenced record
      -> role permission
      -> working hours
      -> overlap (advisory lock, then the exclusion constraint)
      -> booking + job written in one transaction
      -> confirmation email and reminders queued *after* commit (outbox)

A booking created without a technician is PENDING with a NEW job; assigning
someone confirms it. Created with a technician, it is CONFIRMED with a
SCHEDULED job straight away.

Access:
  - BOOKINGS_READ sees every booking in the tenant; BOOKINGS_WRITE changes them;
  - BOOKINGS_OWN (a customer) reaches only their own bookings, and someone
    else's reads exactly like one that does not exist;
  - every referenced customer, service and technician is loaded through the
    caller's organization, and composite foreign keys refuse a mixed-tenant row
    even if a future code path forgot to.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnExpressionArgument, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload, lazyload
from sqlalchemy.orm.interfaces import LoaderOption
from sqlalchemy.sql.elements import ColumnElement

from serviceflow.auth.permissions import Permission as P
from serviceflow.auth.permissions import can
from serviceflow.core.errors import (
    InvalidRole,
    InvalidStateTransition,
    NotFound,
    ScheduleConflict,
    ValidationFailed,
)
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.booking import OPEN_BOOKING_STATUSES, Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.services import audit, notifications, outbox, realtime
from serviceflow.services import jobs as jobs_service
from serviceflow.services.conflicts import is_duplicate_booking_violation, is_overlap_violation
from serviceflow.services.customers import get_customer, get_customer_for_user
from serviceflow.services.recommendations import EmployeeRecommendation, recommend_employees
from serviceflow.services.scheduling import AssignmentRequest, get_scheduling_policy
from serviceflow.services.search import like_pattern
from serviceflow.services.state_machine import transition_booking, transition_job

logger = logging.getLogger(__name__)

# A request further out than this is almost certainly a typo in the year.
MAX_LEAD_DAYS = 365
_ = OPEN_BOOKING_STATUSES  # the statuses the duplicate index covers; see models/booking.py


def booking_window(service: Service, start: datetime) -> tuple[datetime, datetime]:
    """Derive the booking window from the service duration.

    The end time is *always* computed here and never accepted from a client: a
    caller who could choose the end could book a four-hour install into a
    fifteen-minute slot.
    """
    start_utc = start.astimezone(UTC)
    return start_utc, start_utc + timedelta(minutes=service.duration_minutes)


# ----------------------------------------------------------------- loading


def _scoped_customer_id(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """None for tenant-wide readers, otherwise the caller's own customer id."""
    if can(roles, P.BOOKINGS_READ, P.BOOKINGS_WRITE):
        return None
    if can(roles, P.BOOKINGS_OWN):
        return get_customer_for_user(db, organization_id, user_id).id
    raise InvalidRole()


def _booking_options() -> tuple[LoaderOption, ...]:
    return (
        joinedload(Booking.customer).joinedload(Customer.user),
        joinedload(Booking.service),
        joinedload(Booking.job).joinedload(Job.employee).joinedload(Employee.user),
    )


def load_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Booking:
    """Tenant-scoped load with no per-role check.

    Only for call sites the route has already restricted to staff. Anything a
    customer can reach goes through `get_booking`.
    """
    statement = select(Booking).where(
        Booking.id == booking_id, Booking.organization_id == organization_id
    )
    if for_update:
        # The relationships are lazy="joined", and PostgreSQL refuses FOR UPDATE
        # over an outer join, so the lock query loads the row on its own.
        # populate_existing: the booking may already be in this session from an
        # unlocked read; without it the lock would hand back that stale copy.
        statement = (
            statement.options(lazyload("*"))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        statement = statement.options(*_booking_options()).execution_options(populate_existing=True)

    booking = db.scalar(statement)
    if booking is None:
        raise NotFound("We couldn't find that booking.")
    return booking


def get_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    for_update: bool = False,
) -> Booking:
    """Tenant- and role-checked load.

    `for_update` is for the call sites that go on to change the booking, so a
    cancellation and an assignment of the same booking serialise.
    """
    scope = _scoped_customer_id(db, organization_id, roles=roles, user_id=user_id)
    booking = load_booking(db, organization_id, booking_id, for_update=for_update)
    # Someone else's booking reads exactly like one that does not exist.
    if scope is not None and booking.customer_id != scope:
        raise NotFound("We couldn't find that booking.")
    return booking


def _lock_job_for_booking(db: Session, organization_id: uuid.UUID, booking: Booking) -> Job:
    """The job, locked after its booking (the canonical order; see services/jobs.py)."""
    job = db.scalar(
        select(Job)
        .where(Job.booking_id == booking.id, Job.organization_id == organization_id)
        .options(lazyload("*"))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:  # pragma: no cover - every booking is created with its job
        raise NotFound("We couldn't find the job for that booking.")
    return job


def _is_upcoming() -> ColumnElement[bool]:
    """Still ahead: not yet started, not decided against, not finished.

    `list_bookings` filters on this and its exact negation, so every booking falls
    in precisely one of the two timeframes.
    """
    now = datetime.now(UTC)
    finished_job = select(Job.id).where(
        Job.booking_id == Booking.id,
        Job.status.in_([JobStatus.COMPLETED, JobStatus.CANCELLED]),
    )
    return and_(
        Booking.requested_start >= now,
        Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        ~finished_job.exists(),
    )


BOOKING_SORTS = frozenset({"requested_start", "created_at", "status"})


def list_bookings(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    pagination: PageParams,
    status: BookingStatus | None = None,
    timeframe: str | None = None,
    customer_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    sort: SortSpec | None = None,
) -> Page[Booking]:
    filters: list[ColumnExpressionArgument[bool]] = [Booking.organization_id == organization_id]

    scope = _scoped_customer_id(db, organization_id, roles=roles, user_id=user_id)
    if scope is not None:
        if customer_id is not None and customer_id != scope:
            raise InvalidRole("You can only view your own bookings.")
        filters.append(Booking.customer_id == scope)
    elif customer_id is not None:
        filters.append(Booking.customer_id == customer_id)

    if status is not None:
        filters.append(Booking.status == status)
    if service_id is not None:
        filters.append(Booking.service_id == service_id)
    if employee_id is not None:
        filters.append(Booking.job.has(Job.employee_id == employee_id))
    if date_from is not None:
        filters.append(Booking.requested_start >= date_from)
    if date_to is not None:
        filters.append(Booking.requested_start < date_to)

    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                Booking.customer.has(
                    Customer.user.has(
                        or_(
                            User.first_name.ilike(pattern),
                            User.last_name.ilike(pattern),
                            User.email.ilike(pattern),
                            (User.first_name + " " + User.last_name).ilike(pattern),
                        )
                    )
                ),
                Booking.service.has(Service.name.ilike(pattern)),
            )
        )

    if timeframe == "upcoming":
        filters.append(_is_upcoming())
    elif timeframe == "past":
        filters.append(~_is_upcoming())

    total = db.scalar(select(func.count()).select_from(Booking).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Booking)
            .where(*filters)
            .options(*_booking_options())
            .order_by(*_booking_order(sort, timeframe))
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def _booking_order(
    sort: SortSpec | None, timeframe: str | None
) -> list[ColumnExpressionArgument[Any]]:
    """Upcoming reads soonest-first; everything else newest-first."""
    if sort is None:
        default = Booking.requested_start
        ordered = default.asc() if timeframe == "upcoming" else default.desc()
        return [ordered, Booking.id.asc()]

    options: dict[str, InstrumentedAttribute[Any]] = {
        "requested_start": Booking.requested_start,
        "created_at": Booking.created_at,
        "status": Booking.status,
    }
    chosen = options.get(sort.key, Booking.requested_start)
    return [chosen.desc() if sort.descending else chosen.asc(), Booking.id.asc()]


def count_pending(db: Session, organization_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Booking)
            .where(
                Booking.organization_id == organization_id,
                Booking.status == BookingStatus.PENDING,
            )
        )
        or 0
    )


# ----------------------------------------------------------------- creation


def _resolve_bookable_service(
    db: Session, organization_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    service = db.scalar(
        select(Service).where(Service.id == service_id, Service.organization_id == organization_id)
    )
    if service is None:
        raise NotFound("We couldn't find that service.")
    if not service.active:
        raise ValidationFailed(
            f"{service.name} isn't available to book right now.",
            details={"fields": {"service_id": "Service is retired."}},
        )
    return service


def _resolve_employee(db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.organization_id == organization_id
        )
    )
    if employee is None:
        raise NotFound("We couldn't find that employee.")
    return employee


def _resolve_booking_customer(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> Customer:
    if can(roles, P.BOOKINGS_WRITE):
        if customer_id is None:
            raise ValidationFailed(
                "Choose a customer for this booking.",
                details={"fields": {"customer_id": "Required."}},
            )
        customer = get_customer(db, organization_id, customer_id)
    elif can(roles, P.BOOKINGS_OWN):
        customer = get_customer_for_user(db, organization_id, user_id)
        if customer_id is not None and customer_id != customer.id:
            raise InvalidRole("You can only book appointments for yourself.")
    else:
        raise InvalidRole()

    if customer.archived:
        raise ValidationFailed(
            "That customer has been archived. Restore them before booking.",
            details={"fields": {"customer_id": "Customer is archived."}},
        )
    return customer


def validate_start(requested_start: datetime) -> datetime:
    now = datetime.now(UTC)
    start = requested_start.astimezone(UTC)
    if start <= now:
        raise ValidationFailed(
            "Choose a time in the future.",
            details={"fields": {"requested_start": "Must be later than now."}},
        )
    if start > now + timedelta(days=MAX_LEAD_DAYS):
        raise ValidationFailed(
            "That date is too far ahead. Bookings open up to a year in advance.",
            details={"fields": {"requested_start": "Too far in the future."}},
        )
    return start


def _duplicate_message(customer: Customer, service: Service) -> str:
    return f"{customer.user.full_name} already has {service.name} booked at that time."


def create_booking(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    service_id: uuid.UUID,
    requested_start: datetime,
    employee_id: uuid.UUID | None = None,
    customer_notes: str | None = None,
    before_commit: Callable[[Session, Booking], None] | None = None,
) -> Booking:
    """Create a booking and its job in one transaction.

    `before_commit` lets a caller stage more work - the idempotency record -
    inside this same transaction, so the booking and that record commit or roll
    back together.
    """
    customer = _resolve_booking_customer(
        db, organization_id, roles=roles, user_id=user_id, customer_id=customer_id
    )
    service = _resolve_bookable_service(db, organization_id, service_id)
    start, end = booking_window(service, validate_start(requested_start))
    employee = _resolve_employee(db, organization_id, employee_id) if employee_id else None

    # Friendlier than the index violation, and the index still backs it up for
    # the request that races past this check.
    duplicate = db.scalar(
        select(Booking.id).where(
            Booking.organization_id == organization_id,
            Booking.customer_id == customer.id,
            Booking.service_id == service.id,
            Booking.requested_start == start,
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
        )
    )
    if duplicate is not None:
        raise ScheduleConflict(
            _duplicate_message(customer, service),
            details={"reason": "DUPLICATE_BOOKING", "conflicting_booking_id": str(duplicate)},
        )

    booking = Booking(
        organization_id=organization_id,
        customer_id=customer.id,
        service_id=service.id,
        requested_start=start,
        requested_end=end,
        status=BookingStatus.PENDING,
        customer_notes=customer_notes,
    )
    job = Job(
        organization_id=organization_id,
        booking=booking,
        scheduled_start=start,
        scheduled_end=end,
        status=JobStatus.NEW,
    )

    try:
        if employee is not None:
            # Takes the technician's advisory lock, so a concurrent request for
            # the same person waits here and then sees this booking.
            get_scheduling_policy().check_assignment(
                db,
                AssignmentRequest(
                    organization_id=organization_id,
                    employee=employee,
                    service=service,
                    start=start,
                    end=end,
                ),
            )
            transition_booking(booking, BookingStatus.CONFIRMED)
            transition_job(job, JobStatus.SCHEDULED)
            job.employee_id = employee.id

        db.add(booking)
        db.add(job)
        db.flush()
        if before_commit is not None:
            before_commit(db, booking)

        # Staged on the same transaction: if anything fails, nobody is told.
        if employee is None:
            notifications.booking_created(db, booking)
        else:
            notifications.booking_confirmed(db, booking, employee_name=employee.user.full_name)
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            action=AuditAction.BOOKING_CREATED,
            resource_type="booking",
            resource_id=booking.id,
            metadata={
                "service": service.name,
                "customer": customer.user.full_name,
                "requested_start": start.isoformat(),
                "employee": employee.user.full_name if employee else None,
            },
        )
        if employee is not None:
            audit.record(
                db,
                organization_id=organization_id,
                actor_user_id=user_id,
                action=AuditAction.JOB_ASSIGNED,
                resource_type="job",
                resource_id=job.id,
                metadata={"employee": employee.user.full_name},
            )
        outbox.stage_event(
            db,
            realtime.booking_updated(
                organization_id=organization_id,
                booking_id=booking.id,
                customer_user_id=customer.user_id,
                employee_user_id=employee.user_id if employee else None,
            ),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_overlap_violation(exc):
            raise ScheduleConflict(
                "That technician was just booked for overlapping work."
                " Choose another employee or time."
            ) from exc
        if is_duplicate_booking_violation(exc):
            raise ScheduleConflict(
                _duplicate_message(customer, service),
                details={"reason": "DUPLICATE_BOOKING"},
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    logger.info(
        "booking created",
        extra={
            "booking_id": str(booking.id),
            "service_id": str(service.id),
            "assigned": employee is not None,
        },
    )
    return load_booking(db, organization_id, booking.id)


# ----------------------------------------------------------------- assignment


def recommended_employees(
    db: Session, organization_id: uuid.UUID, booking_id: uuid.UUID
) -> list[EmployeeRecommendation]:
    """Rank the qualified employees for a booking's service and window."""
    booking = load_booking(db, organization_id, booking_id)
    return recommend_employees(
        db,
        organization_id,
        service=booking.service,
        start=booking.requested_start,
        end=booking.requested_end,
        exclude_job_id=booking.job.id if booking.job is not None else None,
    )


def confirm_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    admin_notes: str | None = None,
    actor_user_id: uuid.UUID,
) -> Booking:
    """Assign a technician to a pending booking, which confirms it.

    Delegates to `jobs.assign_job`, so confirming from the booking and assigning
    from the job are one code path with one set of rules.
    """
    booking = load_booking(db, organization_id, booking_id)
    if booking.status is not BookingStatus.PENDING:
        raise InvalidStateTransition(
            "This booking isn't waiting for a technician. Reassign its job instead."
        )
    if booking.job is None:  # pragma: no cover - every booking is created with its job
        raise NotFound("We couldn't find the job for that booking.")
    jobs_service.assign_job(
        db,
        organization_id,
        booking.job.id,
        employee_id=employee_id,
        actor_user_id=actor_user_id,
        admin_notes=admin_notes,
        expect_unassigned=True,
    )
    return load_booking(db, organization_id, booking_id)


# ----------------------------------------------------------------- decisions


def reject_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    admin_notes: str | None = None,
) -> Booking:
    booking = load_booking(db, organization_id, booking_id, for_update=True)
    job = _lock_job_for_booking(db, organization_id, booking)
    transition_booking(booking, BookingStatus.REJECTED)
    if job.status is not JobStatus.CANCELLED:
        transition_job(job, JobStatus.CANCELLED)
    if admin_notes is not None:
        booking.admin_notes = admin_notes
    db.flush()
    loaded = load_booking(db, organization_id, booking_id)
    notifications.booking_rejected(db, loaded)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.BOOKING_REJECTED,
        resource_type="booking",
        resource_id=booking.id,
        metadata={"service": loaded.service.name},
    )
    _stage_booking_event(db, loaded)
    db.commit()
    return load_booking(db, organization_id, booking_id)


def cancel_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    reason: str | None = None,
) -> Booking:
    """Cancel a booking and its job.

    Staff with BOOKINGS_WRITE cancel any booking; a customer may cancel their
    own. Refused once work has started: a job in progress or finished cannot be
    cancelled, so neither can its booking.
    """
    if not can(roles, P.BOOKINGS_WRITE, P.BOOKINGS_OWN):
        raise InvalidRole()
    by_staff = can(roles, P.BOOKINGS_WRITE)
    if by_staff:
        booking = load_booking(db, organization_id, booking_id, for_update=True)
    else:
        own = get_customer_for_user(db, organization_id, user_id)
        booking = load_booking(db, organization_id, booking_id, for_update=True)
        if booking.customer_id != own.id:
            raise NotFound("We couldn't find that booking.")

    job = _lock_job_for_booking(db, organization_id, booking)
    if job.status in (JobStatus.IN_PROGRESS, JobStatus.COMPLETED):
        raise InvalidStateTransition(
            "Work on this booking has already started, so it can't be cancelled."
        )
    transition_booking(booking, BookingStatus.CANCELLED)
    if job.status is not JobStatus.CANCELLED:
        transition_job(job, JobStatus.CANCELLED)
    if reason and by_staff:
        booking.admin_notes = (
            f"{booking.admin_notes}\n{reason}".strip() if booking.admin_notes else reason
        )
    db.flush()
    loaded = load_booking(db, organization_id, booking_id)
    notifications.booking_cancelled(db, loaded, cancelled_by_customer=not by_staff)
    _stage_booking_event(db, loaded)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.BOOKING_CANCELLED,
        resource_type="booking",
        resource_id=booking.id,
        metadata={"service": loaded.service.name, "by_customer": not by_staff},
    )
    db.commit()
    logger.info("booking cancelled", extra={"booking_id": str(booking.id)})
    return load_booking(db, organization_id, booking_id)


def reschedule_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    requested_start: datetime,
    actor_user_id: uuid.UUID,
) -> Booking:
    """Move a booking, keeping its job window in step.

    Duration comes from the service, so the new end is recomputed rather than
    shifted blindly - a service whose duration changed gets the current one.
    """
    booking = load_booking(db, organization_id, booking_id, for_update=True)
    if not booking.is_open:
        raise InvalidStateTransition("Only pending or confirmed bookings can be rescheduled.")
    start = validate_start(requested_start)
    job = _lock_job_for_booking(db, organization_id, booking)
    if job.status not in (JobStatus.NEW, JobStatus.SCHEDULED):
        raise InvalidStateTransition("Work on this booking has already started, so it can't move.")

    service = db.scalar(
        select(Service).where(
            Service.id == booking.service_id, Service.organization_id == organization_id
        )
    )
    if service is None:  # pragma: no cover - composite FK guarantees this
        raise NotFound("We couldn't find that service.")

    previous_start = booking.requested_start
    try:
        start, end = booking_window(service, start)
        if job.status is JobStatus.SCHEDULED and job.employee_id is not None:
            employee = db.get(Employee, job.employee_id)
            if employee is None:  # pragma: no cover - composite FK guarantees this
                raise NotFound("We couldn't find that employee.")
            get_scheduling_policy().check_assignment(
                db,
                AssignmentRequest(
                    organization_id=organization_id,
                    employee=employee,
                    service=service,
                    start=start,
                    end=end,
                    exclude_job_id=job.id,
                ),
            )
        booking.requested_start = start
        booking.requested_end = end
        job.scheduled_start = start
        job.scheduled_end = end
        db.flush()

        loaded = load_booking(db, organization_id, booking_id)
        notifications.booking_rescheduled(db, loaded)
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=AuditAction.BOOKING_RESCHEDULED,
            resource_type="booking",
            resource_id=booking.id,
            metadata={"from": previous_start.isoformat(), "to": start.isoformat()},
        )
        _stage_booking_event(db, loaded)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_overlap_violation(exc):
            raise ScheduleConflict(
                "That new time overlaps other work already assigned to this technician."
            ) from exc
        if is_duplicate_booking_violation(exc):
            raise ScheduleConflict(
                "This customer already has the same service booked at that time.",
                details={"reason": "DUPLICATE_BOOKING"},
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    logger.info("booking rescheduled", extra={"booking_id": str(booking.id)})
    return load_booking(db, organization_id, booking_id)


def update_admin_notes(
    db: Session, organization_id: uuid.UUID, booking_id: uuid.UUID, *, admin_notes: str | None
) -> Booking:
    booking = load_booking(db, organization_id, booking_id, for_update=True)
    booking.admin_notes = admin_notes
    db.commit()
    return load_booking(db, organization_id, booking_id)


def _stage_booking_event(db: Session, booking: Booking) -> None:
    outbox.stage_event(
        db,
        realtime.booking_updated(
            organization_id=booking.organization_id,
            booking_id=booking.id,
            customer_user_id=booking.customer.user_id,
            employee_user_id=jobs_service.employee_user_id(booking.job),
        ),
    )
