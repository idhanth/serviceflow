"""Booking and job seeding for the demo organization (PRD 49).

Deterministic given a fixed RNG seed, and idempotent: it tops the organization up
to the target counts rather than appending on every run. Dates are anchored to
today so the demo always looks current, and are built in the organization's own
timezone before being stored as UTC (PRD 40).
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.vehicle import Vehicle

logger = logging.getLogger(__name__)

BOOKING_COUNT = 250
COMPLETED_JOB_COUNT = 180
BUSINESS_HOURS = (8, 16)  # local start hour range
PAST_WINDOW_DAYS = 120
FUTURE_WINDOW_DAYS = 21

CUSTOMER_REQUESTS = [
    None,
    None,
    None,
    "Please pay extra attention to the wheels.",
    "There's a coffee stain on the passenger seat.",
    "Dropping off the night before if that's alright.",
    "Water spots on the hood after the last rain.",
    "Would like the pet hair removed from the back seats.",
    "Getting it ready to sell - whatever makes it shine.",
]


def _local_slot(rng: random.Random, tz: ZoneInfo, day_offset: int) -> datetime:
    """A plausible appointment start, on the half hour, in the shop's timezone."""
    day = (datetime.now(tz) + timedelta(days=day_offset)).date()
    hour = rng.randint(*BUSINESS_HOURS)
    minute = rng.choice([0, 30])
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)


def _qualified(employees: list[Employee], service: Service) -> list[Employee]:
    return [e for e in employees if e.active and any(s.id == service.id for s in e.services)]


def _add_booking(
    db: Session,
    org: Organization,
    *,
    customer: Customer,
    vehicle: Vehicle,
    service: Service,
    start: datetime,
    status: BookingStatus,
    customer_notes: str | None = None,
) -> Booking:
    booking = Booking(
        organization_id=org.id,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        service_id=service.id,
        requested_start=start,
        requested_end=start + timedelta(minutes=service.duration_minutes),
        status=status,
        customer_notes=customer_notes,
    )
    db.add(booking)
    db.flush()
    return booking


def _add_job(
    db: Session,
    org: Organization,
    booking: Booking,
    employee: Employee,
    status: JobStatus,
) -> Job:
    started = completed = None
    if status in (JobStatus.IN_PROGRESS, JobStatus.COMPLETED):
        started = booking.requested_start
    if status is JobStatus.COMPLETED:
        completed = booking.requested_end

    job = Job(
        organization_id=org.id,
        booking_id=booking.id,
        employee_id=employee.id,
        scheduled_start=booking.requested_start,
        scheduled_end=booking.requested_end,
        status=status,
        started_at=started,
        completed_at=completed,
    )
    db.add(job)
    db.flush()
    return job


def _vehicles_by_customer(db: Session, org: Organization) -> dict[uuid.UUID, list[Vehicle]]:
    pairs: dict[uuid.UUID, list[Vehicle]] = {}
    for vehicle in db.scalars(
        select(Vehicle).where(Vehicle.organization_id == org.id, Vehicle.archived_at.is_(None))
    ):
        pairs.setdefault(vehicle.customer_id, []).append(vehicle)
    return pairs


def seed_demo_customer_story(
    db: Session,
    org: Organization,
    rng: random.Random,
    *,
    services: list[Service],
    employees: list[Employee],
    vehicles_by_customer: dict[uuid.UUID, list[Vehicle]],
) -> None:
    """Give the demo customer and demo employee something worth looking at.

    Without this the demo accounts would land on whatever the random distribution
    happened to give them, which is often nothing.
    """
    demo_customer = db.scalar(
        select(Customer)
        .join(Customer.user)
        .where(Customer.organization_id == org.id)
        .where(Customer.user.has(email="customer@serviceflow.demo"))
    )
    demo_employee = db.scalar(
        select(Employee)
        .where(Employee.organization_id == org.id)
        .where(Employee.user.has(email="employee@serviceflow.demo"))
    )
    if demo_customer is None or demo_employee is None:
        return

    fleet = vehicles_by_customer.get(demo_customer.id, [])
    if not fleet:
        return

    tz = ZoneInfo(org.timezone)
    by_name = {service.name: service for service in services}
    existing = db.scalar(
        select(func.count())
        .select_from(Booking)
        .where(Booking.organization_id == org.id, Booking.customer_id == demo_customer.id)
    )
    if existing:
        return

    # A job scheduled today and not yet started, so "Start job" is demoable.
    today = _local_slot(rng, tz, 0)
    booking = _add_booking(
        db,
        org,
        customer=demo_customer,
        vehicle=fleet[0],
        service=by_name["Full Detail"],
        start=today,
        status=BookingStatus.CONFIRMED,
        customer_notes="Please pay extra attention to the wheels.",
    )
    _add_job(db, org, booking, demo_employee, JobStatus.ASSIGNED)

    # A pending request waiting on admin review.
    _add_booking(
        db,
        org,
        customer=demo_customer,
        vehicle=fleet[min(1, len(fleet) - 1)],
        service=by_name["Interior Detail"],
        start=_local_slot(rng, tz, 4),
        status=BookingStatus.PENDING,
        customer_notes="There's a coffee stain on the passenger seat.",
    )

    # Two finished visits, so the customer has history.
    for offset, service_name in ((-30, "Express Wash"), (-75, "Ceramic Coating")):
        service = by_name[service_name]
        candidates = _qualified(employees, service)
        if not candidates:
            continue
        past = _add_booking(
            db,
            org,
            customer=demo_customer,
            vehicle=fleet[0],
            service=service,
            start=_local_slot(rng, tz, offset),
            status=BookingStatus.CONFIRMED,
        )
        _add_job(db, org, past, rng.choice(candidates), JobStatus.COMPLETED)


def seed_bookings(db: Session, org: Organization, rng: random.Random) -> dict[str, int]:
    """Top the organization up to the PRD 49 volumes.

    The composition is planned explicitly rather than rolled per booking, so the
    totals are exact and reproducible instead of approximately right.
    """
    if (
        db.scalar(
            select(func.count()).select_from(Booking).where(Booking.organization_id == org.id)
        )
        or 0
    ) >= BOOKING_COUNT:
        return {"bookings": 0, "jobs": 0}

    services = list(db.scalars(select(Service).where(Service.organization_id == org.id)))
    employees = list(db.scalars(select(Employee).where(Employee.organization_id == org.id)))
    vehicles_by_customer = _vehicles_by_customer(db, org)
    owners = [
        owner
        for owner in (db.get(Customer, customer_id) for customer_id in vehicles_by_customer)
        if owner is not None
    ]
    if not services or not employees or not owners:
        return {"bookings": 0, "jobs": 0}

    tz = ZoneInfo(org.timezone)

    # The demo accounts get their story first; it counts against the budget below.
    seed_demo_customer_story(
        db,
        org,
        rng,
        services=services,
        employees=employees,
        vehicles_by_customer=vehicles_by_customer,
    )

    already = (
        db.scalar(
            select(func.count()).select_from(Booking).where(Booking.organization_id == org.id)
        )
        or 0
    )
    completed_already = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.organization_id == org.id, Job.status == JobStatus.COMPLETED)
        )
        or 0
    )

    remaining = BOOKING_COUNT - already
    completed_needed = max(COMPLETED_JOB_COUNT - completed_already, 0)

    # Split what is left: mostly completed history, then cancellations, rejections
    # and a slice of upcoming work.
    plan: list[str] = ["past_completed"] * min(completed_needed, remaining)
    leftover = remaining - len(plan)
    if leftover > 0:
        shares = [
            ("past_cancelled", 0.34),
            ("past_rejected", 0.20),
            ("future_confirmed", 0.26),
            ("future_pending", 0.20),
        ]
        for label, share in shares[:-1]:
            plan.extend([label] * round(leftover * share))
        plan.extend([shares[-1][0]] * (remaining - len(plan)))
    rng.shuffle(plan)

    created_bookings = 0
    created_jobs = 0

    for kind in plan:
        customer = rng.choice(owners)
        fleet = vehicles_by_customer.get(customer.id, [])
        if not fleet:
            continue
        vehicle = rng.choice(fleet)

        needs_employee = kind in ("past_completed", "future_confirmed")
        if needs_employee:
            # Only offer services someone is actually qualified to perform.
            options = [s for s in services if _qualified(employees, s)]
            if not options:
                continue
            service = rng.choice(options)
            employee = rng.choice(_qualified(employees, service))
        else:
            service = rng.choice(services)
            employee = None

        past = kind.startswith("past")
        offset = -rng.randint(1, PAST_WINDOW_DAYS) if past else rng.randint(1, FUTURE_WINDOW_DAYS)
        start_at = _local_slot(rng, tz, offset)

        status = {
            "past_completed": BookingStatus.CONFIRMED,
            "past_cancelled": BookingStatus.CANCELLED,
            "past_rejected": BookingStatus.REJECTED,
            "future_confirmed": BookingStatus.CONFIRMED,
            "future_pending": BookingStatus.PENDING,
        }[kind]

        booking = _add_booking(
            db,
            org,
            customer=customer,
            vehicle=vehicle,
            service=service,
            start=start_at,
            status=status,
            customer_notes=rng.choice(CUSTOMER_REQUESTS),
        )
        created_bookings += 1

        if employee is not None:
            _add_job(
                db,
                org,
                booking,
                employee,
                JobStatus.COMPLETED if kind == "past_completed" else JobStatus.ASSIGNED,
            )
            created_jobs += 1

    db.flush()
    logger.info("seeded bookings", extra={"bookings": created_bookings, "jobs": created_jobs})
    return {"bookings": created_bookings, "jobs": created_jobs}
