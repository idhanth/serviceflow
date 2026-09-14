"""Booking and job seeding for the demo businesses.

Deterministic given a fixed RNG seed, and idempotent: a business's bookings are
generated once. Dates are anchored to *now* so the demo always looks current,
and are built in the business's own timezone before being stored as UTC.

Every booking gets its job, in the state the product itself would have left it:

    completed history   CONFIRMED booking, COMPLETED job with a technician
    cancelled           CANCELLED booking, CANCELLED job
    rejected            REJECTED booking,  CANCELLED job
    upcoming            CONFIRMED booking, SCHEDULED job with a technician
    waiting             PENDING booking,   NEW job, nobody assigned

Today is built separately so the dashboard and schedule have something real on
them: each technician working today gets a few jobs, and their state follows the
clock - finished before now, under way now, still to come. One job that should
have started is left unstarted, so "running late" has an example.

Nothing here can violate the database's rules: the in-memory `Schedule` refuses
overlaps and hours outside availability before PostgreSQL would.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.seed_data import DEMO_TENANT_SLUG, TenantSpec
from serviceflow.services.availability import (
    DateOverride,
    WeeklyWindow,
    evaluate_window,
    merge,
    windows_for_date,
)

logger = logging.getLogger(__name__)

BUSINESS_HOURS = (7, 17)  # local start-hour range for generated appointments
PAST_WINDOW_DAYS = 120
FUTURE_WINDOW_DAYS = 21
TODAY_JOBS_PER_TECHNICIAN = 3


def _local_slot(rng: random.Random, tz: ZoneInfo, day_offset: int) -> datetime:
    """A plausible appointment start, on the half hour, in the business's timezone."""
    day = (datetime.now(tz) + timedelta(days=day_offset)).date()
    hour = rng.randint(*BUSINESS_HOURS)
    minute = rng.choice([0, 30])
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)


def _qualified(employees: list[Employee], service: Service) -> list[Employee]:
    return [e for e in employees if e.active and any(s.id == service.id for s in e.services)]


class Schedule:
    """Tracks who is busy while seeding, so generated jobs never overlap."""

    def __init__(self, timezone: str) -> None:
        self.timezone = timezone
        self._busy: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
        self._weekly: dict[uuid.UUID, list[WeeklyWindow]] = {}
        self._overrides: dict[uuid.UUID, dict[dt.date, DateOverride]] = {}

    def load(self, employees: list[Employee]) -> None:
        for employee in employees:
            self._weekly[employee.id] = [
                WeeklyWindow(
                    day_of_week=window.day_of_week,
                    start_time=window.start_time,
                    end_time=window.end_time,
                )
                for window in employee.availability
            ]
            self._overrides[employee.id] = {
                override.date: DateOverride(
                    date=override.date,
                    available=override.available,
                    start_time=override.start_time,
                    end_time=override.end_time,
                    reason=override.reason,
                )
                for override in employee.availability_overrides
            }
            self._busy.setdefault(employee.id, [])

    def windows_on(self, employee: Employee, date: dt.date) -> list[tuple[datetime, datetime]]:
        """The employee's working windows on a local date, as UTC instants."""
        tz = ZoneInfo(self.timezone)
        override = self._overrides.get(employee.id, {}).get(date)
        windows = merge(windows_for_date(date, self._weekly.get(employee.id, []), override))
        midnight = datetime.combine(date, time.min, tzinfo=tz)
        return [
            (
                (midnight + timedelta(minutes=w.start)).astimezone(UTC),
                (midnight + timedelta(minutes=w.end)).astimezone(UTC),
            )
            for w in windows
        ]

    def free(self, employee: Employee, start: datetime, end: datetime) -> bool:
        if any(s < end and e > start for s, e in self._busy.get(employee.id, [])):
            return False
        return evaluate_window(
            start,
            end,
            timezone=self.timezone,
            weekly=self._weekly.get(employee.id, []),
            overrides=self._overrides.get(employee.id, {}),
        ).available

    def take(self, employee: Employee, start: datetime, end: datetime) -> None:
        self._busy.setdefault(employee.id, []).append((start, end))

    def pick(
        self, rng: random.Random, candidates: list[Employee], start: datetime, end: datetime
    ) -> Employee | None:
        # Sorted by a *natural* key, not by id: primary keys are fresh UUIDs on
        # every rebuild, so ordering by them would hand rng.shuffle a different
        # starting list each time and the "fixed seed" would reproduce nothing.
        order = sorted(candidates, key=lambda e: e.user.email)
        rng.shuffle(order)
        for employee in order:
            if self.free(employee, start, end):
                return employee
        return None


class Writer:
    """Adds bookings with their jobs, refusing exact duplicates of open bookings."""

    def __init__(self, db: Session, org: Organization) -> None:
        self.db = db
        self.org = org
        self.open_keys: set[tuple[uuid.UUID, uuid.UUID, datetime]] = set()
        self.bookings = 0

    def add(
        self,
        *,
        customer: Customer,
        service: Service,
        start: datetime,
        booking_status: BookingStatus,
        job_status: JobStatus,
        employee: Employee | None = None,
        customer_notes: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> Booking | None:
        key = (customer.id, service.id, start)
        is_open = booking_status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
        if is_open and key in self.open_keys:
            return None
        end = start + timedelta(minutes=service.duration_minutes)
        booking = Booking(
            organization_id=self.org.id,
            customer_id=customer.id,
            service_id=service.id,
            requested_start=start,
            requested_end=end,
            status=booking_status,
            customer_notes=customer_notes,
        )
        self.db.add(booking)
        self.db.flush()
        self.db.add(
            Job(
                organization_id=self.org.id,
                booking_id=booking.id,
                employee_id=employee.id if employee else None,
                scheduled_start=start,
                scheduled_end=end,
                status=job_status,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
        if is_open:
            self.open_keys.add(key)
        self.bookings += 1
        return booking


def _seed_today(
    rng: random.Random,
    *,
    writer: Writer,
    schedule: Schedule,
    employees: list[Employee],
    services: list[Service],
    customers: list[Customer],
    spec: TenantSpec,
) -> int:
    """A few jobs per technician working today, in the state the clock implies."""
    tz = ZoneInfo(schedule.timezone)
    now = datetime.now(UTC)
    today = now.astimezone(tz).date()
    late_left = 1
    created = 0

    for employee in sorted(employees, key=lambda e: e.user.email):
        qualified = [s for s in services if any(q.id == s.id for q in employee.services)]
        if not qualified:
            continue
        placed = 0
        for window_start, window_end in schedule.windows_on(employee, today):
            cursor = window_start
            while placed < TODAY_JOBS_PER_TECHNICIAN and cursor < window_end:
                service = rng.choice(qualified)
                end = cursor + timedelta(minutes=service.duration_minutes)
                if end > window_end:
                    break
                if schedule.free(employee, cursor, end):
                    if end <= now:
                        status, started, completed = JobStatus.COMPLETED, cursor, end
                    elif cursor <= now - timedelta(minutes=20) and late_left:
                        # Should have started and hasn't: the dashboard's "running late".
                        status, started, completed = JobStatus.SCHEDULED, None, None
                        late_left -= 1
                    elif cursor <= now:
                        status, started, completed = JobStatus.IN_PROGRESS, cursor, None
                    else:
                        status, started, completed = JobStatus.SCHEDULED, None, None
                    booking = writer.add(
                        customer=rng.choice(customers),
                        service=service,
                        start=cursor,
                        booking_status=BookingStatus.CONFIRMED,
                        job_status=status,
                        employee=employee,
                        customer_notes=rng.choice(spec["customer_requests"]),
                        started_at=started,
                        completed_at=completed,
                    )
                    if booking is not None:
                        schedule.take(employee, cursor, end)
                        placed += 1
                        created += 1
                # A gap for travel between visits, as a dispatcher would leave.
                cursor = end + timedelta(minutes=rng.choice([30, 45, 60]))
    return created


def _seed_demo_customer(
    rng: random.Random,
    *,
    writer: Writer,
    schedule: Schedule,
    employees: list[Employee],
    services: dict[str, Service],
    customer: Customer,
) -> None:
    """Give the demo customer an upcoming visit, a request, and some history."""
    tz = ZoneInfo(schedule.timezone)
    technician = next((e for e in employees if e.user.email == "employee@serviceflow.demo"), None)

    plans = [
        (2, "HVAC Inspection", BookingStatus.CONFIRMED, JobStatus.SCHEDULED, technician),
        (5, "Drain Cleaning", BookingStatus.PENDING, JobStatus.NEW, None),
        (-21, "Preventive Maintenance", BookingStatus.CONFIRMED, JobStatus.COMPLETED, None),
        (-64, "Electrical Safety Inspection", BookingStatus.CONFIRMED, JobStatus.COMPLETED, None),
        (-140, "HVAC Inspection", BookingStatus.CONFIRMED, JobStatus.COMPLETED, technician),
        (-40, "Consultation", BookingStatus.CANCELLED, JobStatus.CANCELLED, None),
    ]
    for offset, service_name, booking_status, job_status, preferred in plans:
        service = services.get(service_name)
        if service is None:
            continue
        needs_technician = job_status in (JobStatus.SCHEDULED, JobStatus.COMPLETED)
        for _ in range(80):
            start = _local_slot(rng, tz, offset)
            end = start + timedelta(minutes=service.duration_minutes)
            employee = None
            if needs_technician:
                candidates = (
                    [preferred] if preferred is not None else _qualified(employees, service)
                )
                employee = schedule.pick(rng, candidates, start, end)
                if employee is None:
                    continue
            booking = writer.add(
                customer=customer,
                service=service,
                start=start,
                booking_status=booking_status,
                job_status=job_status,
                employee=employee,
                customer_notes="The upstairs AC isn't keeping up in the afternoons."
                if offset == 2
                else None,
                started_at=start if job_status is JobStatus.COMPLETED else None,
                completed_at=end if job_status is JobStatus.COMPLETED else None,
            )
            if booking is not None and employee is not None:
                schedule.take(employee, start, end)
            break


def seed_bookings(
    db: Session, org: Organization, spec: TenantSpec, rng: random.Random
) -> dict[str, int]:
    if db.scalar(
        select(func.count()).select_from(Booking).where(Booking.organization_id == org.id)
    ):
        return {"bookings": 0}

    services = list(
        db.scalars(select(Service).where(Service.organization_id == org.id).order_by(Service.name))
    )
    employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.organization_id == org.id)
            .join(Employee.user)
            .options(
                selectinload(Employee.services),
                selectinload(Employee.availability),
                selectinload(Employee.availability_overrides),
            )
            .order_by(User.email)
        ).unique()
    )
    customers = list(
        db.scalars(
            select(Customer)
            .where(Customer.organization_id == org.id)
            .join(Customer.user)
            .order_by(User.email)
        ).unique()
    )
    if not services or not employees or not customers:
        return {"bookings": 0}

    tz = ZoneInfo(org.timezone)
    schedule = Schedule(org.timezone)
    schedule.load(employees)
    writer = Writer(db, org)

    demo = next((c for c in customers if c.user.email == "customer@serviceflow.demo"), None)
    others = [c for c in customers if c is not demo] or customers
    if spec["slug"] == DEMO_TENANT_SLUG and demo is not None:
        _seed_demo_customer(
            rng,
            writer=writer,
            schedule=schedule,
            employees=employees,
            services={s.name: s for s in services},
            customer=demo,
        )

    today = _seed_today(
        rng,
        writer=writer,
        schedule=schedule,
        employees=employees,
        services=services,
        customers=others,
        spec=spec,
    )

    # The rest of the history is planned explicitly rather than rolled per
    # booking, so the totals are exact and reproducible.
    composition = cast(dict[str, int], spec["composition"])
    plan = [kind for kind, count in composition.items() for _ in range(count)]
    rng.shuffle(plan)

    outcome = {
        "past_completed": (BookingStatus.CONFIRMED, JobStatus.COMPLETED),
        "past_cancelled": (BookingStatus.CANCELLED, JobStatus.CANCELLED),
        "past_rejected": (BookingStatus.REJECTED, JobStatus.CANCELLED),
        "future_confirmed": (BookingStatus.CONFIRMED, JobStatus.SCHEDULED),
        "future_pending": (BookingStatus.PENDING, JobStatus.NEW),
    }
    queue = list(plan)
    attempts = 0
    while queue and attempts < len(plan) * 12:
        attempts += 1
        kind = queue.pop(0)
        booking_status, job_status = outcome[kind]
        past = kind.startswith("past")
        offset_range = (-PAST_WINDOW_DAYS, -1) if past else (1, FUTURE_WINDOW_DAYS)
        customer = rng.choice(others)

        employee: Employee | None = None
        if job_status in (JobStatus.COMPLETED, JobStatus.SCHEDULED):
            options = [s for s in services if _qualified(employees, s)]
            service = rng.choice(options)
            for _ in range(80):
                start = _local_slot(rng, tz, rng.randint(*offset_range))
                end = start + timedelta(minutes=service.duration_minutes)
                employee = schedule.pick(rng, _qualified(employees, service), start, end)
                if employee is not None:
                    break
            if employee is None:
                # Nobody free in that stretch of the calendar: retry the slot later
                # rather than downgrading it, so the composition stays exact.
                queue.append(kind)
                continue
        else:
            service = rng.choice(services)
            start = _local_slot(rng, tz, rng.randint(*offset_range))
            end = start + timedelta(minutes=service.duration_minutes)

        booking = writer.add(
            customer=customer,
            service=service,
            start=start,
            booking_status=booking_status,
            job_status=job_status,
            employee=employee,
            customer_notes=rng.choice(spec["customer_requests"]),
            started_at=start if job_status is JobStatus.COMPLETED else None,
            completed_at=end if job_status is JobStatus.COMPLETED else None,
        )
        if booking is None:
            queue.append(kind)
            continue
        if employee is not None:
            schedule.take(employee, start, end)

    db.flush()
    logger.info(
        "seeded bookings", extra={"slug": spec["slug"], "bookings": writer.bookings, "today": today}
    )
    return {"bookings": writer.bookings, "today_jobs": today}
