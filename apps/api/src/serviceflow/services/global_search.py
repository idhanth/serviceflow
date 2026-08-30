"""Global admin search across the record types an admin looks things up by (PRD 32).

Plain PostgreSQL `ILIKE` over a handful of indexed columns, capped per group.
At this scale - hundreds of customers, thousands of bookings - that is both fast
enough and exactly predictable, which a relevance-ranked engine would not be.
There is no Elasticsearch here because there is no problem that needs one.

Every query is filtered by organization, so a result can never cross tenants.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle
from serviceflow.services.search import like_pattern

MIN_QUERY_LENGTH = 2
PER_GROUP_LIMIT = 5


@dataclass(frozen=True, slots=True)
class SearchHit:
    kind: str  # customer | vehicle | booking | job | employee | service
    id: uuid.UUID
    title: str
    subtitle: str
    href: str


def _full_name() -> ColumnElement[str]:
    """first + ' ' + last, so "Grace Hopper" matches as one term."""
    return User.first_name + " " + User.last_name


def search(db: Session, organization_id: uuid.UUID, term: str) -> list[SearchHit]:
    term = term.strip()
    if len(term) < MIN_QUERY_LENGTH:
        return []
    pattern = like_pattern(term)
    hits: list[SearchHit] = []

    customers = db.scalars(
        select(Customer)
        .join(User)
        .where(
            Customer.organization_id == organization_id,
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
                _full_name().ilike(pattern),
            ),
        )
        .order_by(User.first_name, User.last_name)
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="customer",
            id=row.id,
            title=row.user.full_name,
            subtitle=row.user.email,
            href="/customers",
        )
        for row in customers
    ]

    vehicles = db.scalars(
        select(Vehicle)
        .where(
            Vehicle.organization_id == organization_id,
            Vehicle.archived_at.is_(None),
            or_(
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
                Vehicle.color.ilike(pattern),
                Vehicle.license_plate.ilike(pattern),
            ),
        )
        .order_by(Vehicle.created_at.desc())
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="vehicle",
            id=row.id,
            title=row.display_name,
            subtitle=row.license_plate or row.color or "No plate on file",
            href="/vehicles",
        )
        for row in vehicles
    ]

    employees = db.scalars(
        select(Employee)
        .join(User)
        .where(
            Employee.organization_id == organization_id,
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
                Employee.job_title.ilike(pattern),
                _full_name().ilike(pattern),
            ),
        )
        .order_by(Employee.active.desc(), User.first_name)
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="employee",
            id=row.id,
            title=row.user.full_name,
            subtitle=row.job_title if row.active else f"{row.job_title} (inactive)",
            href="/employees",
        )
        for row in employees
    ]

    services = db.scalars(
        select(Service)
        .where(
            Service.organization_id == organization_id,
            or_(Service.name.ilike(pattern), Service.description.ilike(pattern)),
        )
        .order_by(Service.active.desc(), Service.name)
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="service",
            id=row.id,
            title=row.name,
            subtitle=f"{row.duration_minutes} min",
            href="/services",
        )
        for row in services
    ]

    # Bookings and jobs are looked up by who or what they are for.
    bookings = db.scalars(
        select(Booking)
        .join(Customer, Customer.id == Booking.customer_id)
        .join(User, User.id == Customer.user_id)
        .join(Vehicle, Vehicle.id == Booking.vehicle_id)
        .join(Service, Service.id == Booking.service_id)
        .where(
            Booking.organization_id == organization_id,
            or_(
                _full_name().ilike(pattern),
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
                Vehicle.license_plate.ilike(pattern),
                Service.name.ilike(pattern),
            ),
        )
        .order_by(Booking.requested_start.desc())
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="booking",
            id=row.id,
            title=f"{row.service.name} — {row.customer.user.full_name}",
            subtitle=(
                f"{row.requested_start.astimezone(UTC):%d %b %Y} · {row.status.value.lower()}"
            ),
            href="/bookings",
        )
        for row in bookings
    ]

    jobs = db.scalars(
        select(Job)
        .join(Booking, Booking.id == Job.booking_id)
        .join(Customer, Customer.id == Booking.customer_id)
        .join(User, User.id == Customer.user_id)
        .join(Service, Service.id == Booking.service_id)
        .where(
            Job.organization_id == organization_id,
            or_(_full_name().ilike(pattern), Service.name.ilike(pattern)),
        )
        .order_by(Job.scheduled_start.desc())
        .limit(PER_GROUP_LIMIT)
    ).unique()
    hits += [
        SearchHit(
            kind="job",
            id=row.id,
            title=f"{row.booking.service.name} — {row.booking.customer.user.full_name}",
            subtitle=(
                f"{row.scheduled_start.astimezone(UTC):%d %b %Y} · {row.employee.user.full_name}"
            ),
            href=f"/jobs/{row.id}",
        )
        for row in jobs
    ]

    return hits
