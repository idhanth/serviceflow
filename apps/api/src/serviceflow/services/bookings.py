"""Booking workflow: request, review, confirm, reject, cancel, reschedule.

Access rules enforced here rather than in routes (PRD 6, 61):
  - a customer only ever reaches their own bookings;
  - an admin reaches every booking in the active organization;
  - every referenced customer, vehicle, service and employee is re-checked to
    belong to that organization before it is used.
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

from serviceflow.core.errors import (
    Forbidden,
    InvalidStateTransition,
    NotFound,
    ScheduleConflict,
    ValidationFailed,
)
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle
from serviceflow.services import audit, notifications, outbox, realtime
from serviceflow.services.conflicts import is_overlap_violation
from serviceflow.services.customers import get_customer, get_customer_for_user
from serviceflow.services.recommendations import EmployeeRecommendation, recommend_employees
from serviceflow.services.scheduling import AssignmentRequest, get_scheduling_policy
from serviceflow.services.search import like_pattern
from serviceflow.services.state_machine import transition_booking, transition_job

logger = logging.getLogger(__name__)

# A request further out than this is almost certainly a typo in the year.
MAX_LEAD_DAYS = 365


def booking_window(service: Service, start: datetime) -> tuple[datetime, datetime]:
    """Derive the booking window from the service duration.

    The end time is *always* computed here and never accepted from a client
    (PRD 8): a caller who could choose the end could book a four-hour detail into
    a fifteen-minute slot.
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
    """None for an admin (organization-wide), otherwise the caller's own id.

    Employees have no booking access at all (PRD 6), so they are refused here
    rather than falling through to a confusing "no customer profile" 404.
    """
    if Role.ADMIN in roles:
        return None
    if Role.CUSTOMER not in roles:
        raise Forbidden()
    return get_customer_for_user(db, organization_id, user_id).id


def _booking_options() -> tuple[LoaderOption, ...]:
    return (
        joinedload(Booking.customer).joinedload(Customer.user),
        joinedload(Booking.vehicle),
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

    Only for call sites the route has already restricted to admins. Anything a
    customer can reach must go through `get_booking`.
    """
    statement = select(Booking).where(
        Booking.id == booking_id, Booking.organization_id == organization_id
    )
    if for_update:
        # The relationships are lazy="joined", and PostgreSQL refuses FOR UPDATE
        # over an outer join, so the lock query loads the row on its own.
        statement = statement.options(lazyload("*")).with_for_update()
    else:
        statement = statement.options(*_booking_options())

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

    `for_update` is for the call sites that go on to change the booking. Without
    it a cancellation can read the booking while a confirmation is still in
    flight, decide there is no job to cancel, and commit - leaving a cancelled
    booking holding a live job. Locking makes the two serialise.
    """
    booking = load_booking(db, organization_id, booking_id, for_update=for_update)

    if Role.ADMIN not in roles:
        if Role.CUSTOMER not in roles:
            raise Forbidden()
        own = get_customer_for_user(db, organization_id, user_id)
        # Someone else's booking reads exactly like one that does not exist.
        if booking.customer_id != own.id:
            raise NotFound("We couldn't find that booking.")
    return booking


def _is_upcoming() -> ColumnElement[bool]:
    """Still ahead of the customer: not yet started, not decided against, not finished.

    `list_bookings` filters on this and its exact negation, so every booking falls
    in precisely one of the two timeframes - a job completed ahead of its slot
    moves to history rather than disappearing from both.
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
    q: str | None = None,
    sort: SortSpec | None = None,
) -> Page[Booking]:
    filters = [Booking.organization_id == organization_id]

    scope = _scoped_customer_id(db, organization_id, roles=roles, user_id=user_id)
    if scope is not None:
        if customer_id is not None and customer_id != scope:
            raise Forbidden("You can only view your own bookings.")
        filters.append(Booking.customer_id == scope)
    elif customer_id is not None:
        get_customer(db, organization_id, customer_id)  # 404s on a foreign id
        filters.append(Booking.customer_id == customer_id)

    if status is not None:
        filters.append(Booking.status == status)

    if q:
        # Bookings are looked up by who they are for and what they are.
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
                Booking.vehicle.has(
                    or_(
                        Vehicle.make.ilike(pattern),
                        Vehicle.model.ilike(pattern),
                        Vehicle.license_plate.ilike(pattern),
                    )
                ),
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


BOOKING_SORTS = frozenset({"requested_start", "created_at", "status"})


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


def _resolve_bookable_vehicle(
    db: Session, organization_id: uuid.UUID, customer: Customer, vehicle_id: uuid.UUID
) -> Vehicle:
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organization_id == organization_id)
    )
    # A vehicle belonging to someone else is reported as unknown, not as forbidden,
    # so booking cannot be used to discover other customers' vehicle ids.
    if vehicle is None or vehicle.customer_id != customer.id:
        raise NotFound("We couldn't find that vehicle.")
    if vehicle.archived:
        raise ValidationFailed(
            "That vehicle has been removed from the account.",
            details={"fields": {"vehicle_id": "Vehicle is archived."}},
        )
    return vehicle


def create_booking(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    vehicle_id: uuid.UUID,
    service_id: uuid.UUID,
    requested_start: datetime,
    customer_notes: str | None = None,
    before_commit: Callable[[Session, Booking], None] | None = None,
) -> Booking:
    """Create a pending booking.

    `before_commit` lets a caller stage more work - the idempotency record -
    inside this same transaction, so the booking and that record commit or roll
    back together.
    """
    if Role.ADMIN in roles:
        if customer_id is None:
            raise ValidationFailed(
                "Choose a customer for this booking.",
                details={"fields": {"customer_id": "Required."}},
            )
        customer = get_customer(db, organization_id, customer_id)
    else:
        customer = get_customer_for_user(db, organization_id, user_id)
        if customer_id is not None and customer_id != customer.id:
            raise Forbidden("You can only book for yourself.")

    service = _resolve_bookable_service(db, organization_id, service_id)
    vehicle = _resolve_bookable_vehicle(db, organization_id, customer, vehicle_id)

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

    start, end = booking_window(service, start)
    booking = Booking(
        organization_id=organization_id,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        service_id=service.id,
        requested_start=start,
        requested_end=end,
        status=BookingStatus.PENDING,
        customer_notes=customer_notes,
    )
    db.add(booking)
    db.flush()
    if before_commit is not None:
        before_commit(db, booking)
    # Staged on the same transaction: if the insert fails, nobody is told.
    notifications.booking_created(db, booking)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.BOOKING_CREATED,
        resource_type="booking",
        resource_id=booking.id,
        metadata={
            "service": service.name,
            "vehicle": vehicle.display_name,
            "requested_start": start.isoformat(),
        },
    )
    outbox.stage_event(
        db,
        realtime.booking_updated(
            organization_id=organization_id,
            booking_id=booking.id,
            customer_user_id=booking.customer.user_id,
            employee_user_id=booking.job.employee.user_id if booking.job else None,
        ),
    )
    db.commit()
    db.refresh(booking)
    logger.info(
        "booking created",
        extra={"booking_id": str(booking.id), "service_id": str(service.id)},
    )
    return booking


# ----------------------------------------------------------------- assignment


def recommended_employees(
    db: Session, organization_id: uuid.UUID, booking_id: uuid.UUID
) -> list[EmployeeRecommendation]:
    """Rank the qualified employees for a booking's service and window (PRD 11)."""
    booking = load_booking(db, organization_id, booking_id)
    service = db.get(Service, booking.service_id)
    if service is None:  # pragma: no cover - FK guarantees this
        raise NotFound("We couldn't find that service.")

    return recommend_employees(
        db,
        organization_id,
        service=service,
        start=booking.requested_start,
        end=booking.requested_end,
        exclude_job_id=booking.job.id if booking.job is not None else None,
    )


def _load_employee_for_assignment(
    db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID
) -> Employee:
    employee = db.scalar(
        select(Employee).where(
            Employee.id == employee_id, Employee.organization_id == organization_id
        )
    )
    if employee is None:
        raise NotFound("We couldn't find that employee.")
    return employee


# ----------------------------------------------------------------- decisions


def confirm_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    employee_id: uuid.UUID,
    admin_notes: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Booking:
    """Confirm a booking and create its job in one transaction.

    Three things guarantee "a confirmed booking always has exactly one job":
      1. the booking row is locked for the duration, so two concurrent confirms
         serialise rather than interleave;
      2. the state machine refuses a second CONFIRMED transition;
      3. `jobs.booking_id` is unique, so even a bug that got past both would fail
         in the database rather than produce a duplicate.
    Everything below happens in a single transaction: if job creation raises, the
    booking stays PENDING.
    """
    booking = load_booking(db, organization_id, booking_id, for_update=True)

    try:
        transition_booking(booking, BookingStatus.CONFIRMED)

        employee = _load_employee_for_assignment(db, organization_id, employee_id)
        service = db.get(Service, booking.service_id)
        if service is None:  # pragma: no cover - FK guarantees this
            raise NotFound("We couldn't find that service.")

        # The phase 4 scheduling engine plugs in here, inside this transaction.
        get_scheduling_policy().check_assignment(
            db,
            AssignmentRequest(
                organization_id=organization_id,
                employee=employee,
                service=service,
                start=booking.requested_start,
                end=booking.requested_end,
            ),
        )

        if admin_notes is not None:
            booking.admin_notes = admin_notes

        job = Job(
            organization_id=organization_id,
            booking_id=booking.id,
            employee_id=employee.id,
            scheduled_start=booking.requested_start,
            scheduled_end=booking.requested_end,
            status=JobStatus.ASSIGNED,
        )
        db.add(job)
        db.flush()
        notifications.booking_confirmed(db, booking, employee_name=employee.user.full_name)
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=AuditAction.BOOKING_CONFIRMED,
            resource_type="booking",
            resource_id=booking.id,
            metadata={
                "employee": employee.user.full_name,
                "scheduled_start": booking.requested_start.isoformat(),
            },
        )
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=AuditAction.JOB_ASSIGNED,
            # Filed against the job, like every other JOB_* entry, so filtering
            # the feed by a job id shows its whole life including this.
            resource_type="job",
            resource_id=job.id,
            metadata={"employee": employee.user.full_name},
        )
        outbox.stage_event(
            db,
            realtime.booking_updated(
                organization_id=organization_id,
                booking_id=booking.id,
                customer_user_id=booking.customer.user_id,
                employee_user_id=employee.user_id,
            ),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Two different constraints can fire here, and they mean different things.
        if is_overlap_violation(exc):
            # The exclusion constraint caught a schedule clash the policy missed -
            # only reachable if a competing transaction committed in between.
            raise ScheduleConflict(
                "That technician was just assigned overlapping work."
                " Pick someone else, or a different time."
            ) from exc
        # The unique constraint fired: another request confirmed this booking.
        raise InvalidStateTransition("This booking has already been confirmed.") from exc
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    logger.info(
        "booking confirmed",
        extra={"booking_id": str(booking.id), "employee_id": str(employee_id)},
    )
    return load_booking(db, organization_id, booking_id)


def reject_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    admin_notes: str | None = None,
) -> Booking:
    # Locked for the same reason cancellation is: a rejection racing a
    # confirmation must serialise, not interleave.
    booking = get_booking(
        db, organization_id, booking_id, roles=roles, user_id=user_id, for_update=True
    )
    transition_booking(booking, BookingStatus.REJECTED)
    if admin_notes is not None:
        booking.admin_notes = admin_notes
    notifications.booking_rejected(db, booking)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.BOOKING_REJECTED,
        resource_type="booking",
        resource_id=booking.id,
        metadata={"service": booking.service.name},
    )
    outbox.stage_event(
        db,
        realtime.booking_updated(
            organization_id=organization_id,
            booking_id=booking.id,
            customer_user_id=booking.customer.user_id,
            employee_user_id=booking.job.employee.user_id if booking.job else None,
        ),
    )
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    reason: str | None = None,
) -> Booking:
    """Cancel a booking, and its job if one exists.

    Refused once the work has started: a job that is in progress or finished
    cannot be cancelled (PRD 12), so neither can its booking.
    """
    booking = get_booking(
        db, organization_id, booking_id, roles=roles, user_id=user_id, for_update=True
    )

    job = booking.job
    if job is not None and job.status is not JobStatus.CANCELLED:
        if job.status is not JobStatus.ASSIGNED:
            raise InvalidStateTransition(
                "Work on this booking has already started, so it can't be cancelled."
                " Ask an admin to close it out instead."
            )
        transition_job(job, JobStatus.CANCELLED)

    transition_booking(booking, BookingStatus.CANCELLED)
    if reason:
        booking.admin_notes = (
            f"{booking.admin_notes}\n{reason}".strip() if booking.admin_notes else reason
        )
    notifications.booking_cancelled(db, booking, cancelled_by_customer=Role.ADMIN not in roles)
    outbox.stage_event(
        db,
        realtime.booking_updated(
            organization_id=organization_id,
            booking_id=booking.id,
            customer_user_id=booking.customer.user_id,
            employee_user_id=booking.job.employee.user_id if booking.job else None,
        ),
    )
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.BOOKING_CANCELLED,
        resource_type="booking",
        resource_id=booking.id,
        metadata={
            "service": booking.service.name,
            "by_customer": Role.ADMIN not in roles,
        },
    )
    db.commit()
    db.refresh(booking)
    logger.info("booking cancelled", extra={"booking_id": str(booking.id)})
    return booking


def reschedule_booking(
    db: Session,
    organization_id: uuid.UUID,
    booking_id: uuid.UUID,
    *,
    requested_start: datetime,
    actor_user_id: uuid.UUID | None = None,
) -> Booking:
    """Move a booking, keeping its job window in step.

    Duration comes from the service, so the new end is recomputed rather than
    shifted blindly - a service whose duration changed gets the current one.
    """
    booking = load_booking(db, organization_id, booking_id, for_update=True)
    if not booking.is_open:
        raise InvalidStateTransition("Only pending or confirmed bookings can be rescheduled.")

    start = requested_start.astimezone(UTC)
    if start <= datetime.now(UTC):
        raise ValidationFailed(
            "Choose a time in the future.",
            details={"fields": {"requested_start": "Must be later than now."}},
        )

    service = db.get(Service, booking.service_id)
    if service is None:  # pragma: no cover - FK guarantees this
        raise NotFound("We couldn't find that service.")

    previous_start = booking.requested_start
    try:
        start, end = booking_window(service, start)
        booking.requested_start = start
        booking.requested_end = end

        job = booking.job
        if job is not None and job.status is JobStatus.ASSIGNED:
            get_scheduling_policy().check_assignment(
                db,
                AssignmentRequest(
                    organization_id=organization_id,
                    employee=job.employee,
                    service=service,
                    start=start,
                    end=end,
                    exclude_job_id=job.id,
                ),
            )
            job.scheduled_start = start
            job.scheduled_end = end
        elif job is not None:
            raise InvalidStateTransition(
                "Work on this booking has already started, so it can't be moved."
            )
        notifications.booking_rescheduled(db, booking)
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=AuditAction.BOOKING_RESCHEDULED,
            resource_type="booking",
            resource_id=booking.id,
            metadata={"from": previous_start.isoformat(), "to": start.isoformat()},
        )
        outbox.stage_event(
            db,
            realtime.booking_updated(
                organization_id=organization_id,
                booking_id=booking.id,
                customer_user_id=booking.customer.user_id,
                employee_user_id=booking.job.employee.user_id if booking.job else None,
            ),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if is_overlap_violation(exc):
            raise ScheduleConflict(
                "That new time overlaps other work already assigned to this technician."
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    logger.info("booking rescheduled", extra={"booking_id": str(booking.id)})
    return load_booking(db, organization_id, booking_id)


def update_admin_notes(
    db: Session, organization_id: uuid.UUID, booking_id: uuid.UUID, *, admin_notes: str | None
) -> Booking:
    booking = load_booking(db, organization_id, booking_id)
    booking.admin_notes = admin_notes
    db.commit()
    db.refresh(booking)
    return booking
