"""Idempotent development seed.

Phase 1 seeded the organization and the three demo logins from PRD 50; phase 2
adds the service catalog, employees, customers and vehicles at the volumes in
PRD 49. Running it repeatedly must not duplicate anything, so every step is an
upsert keyed on a natural identifier.
"""

from __future__ import annotations

import logging
import random
import string

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.auth.passwords import hash_password
from serviceflow.core.logging import configure_logging
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import JobStatus, MembershipStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.job_note import JobNote
from serviceflow.db.models.job_photo import JobPhoto
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle
from serviceflow.db.seed_audit import seed_audit_trail
from serviceflow.db.seed_availability import seed_availability
from serviceflow.db.seed_bookings import seed_bookings
from serviceflow.db.seed_content import seed_job_content, seed_notifications
from serviceflow.db.seed_data import (
    COLORS,
    CUSTOMER_NOTES,
    EMPLOYEES,
    FIRST_NAMES,
    LAST_NAMES,
    SERVICES,
    VEHICLE_MODELS,
)

logger = logging.getLogger(__name__)

DEMO_ORG_SLUG = "gleam-auto-detailing"
DEMO_PASSWORD = "demo1234"
CUSTOMER_COUNT = 75
VEHICLE_COUNT = 100
SEED = 20260829  # fixed so reseeding a fresh database reproduces the same demo

DEMO_USERS: list[tuple[str, str, str, Role]] = [
    ("admin@serviceflow.demo", "Alex", "Rivera", Role.ADMIN),
    ("employee@serviceflow.demo", "Maria", "Santos", Role.EMPLOYEE),
    ("customer@serviceflow.demo", "Jordan", "Blake", Role.CUSTOMER),
]


def upsert_organization(db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    if org is None:
        org = Organization(
            name="Gleam Auto Detailing",
            slug=DEMO_ORG_SLUG,
            email="hello@gleamdetailing.demo",
            phone="+1 (415) 555-0142",
            timezone="America/Los_Angeles",
            address="1820 Harrison St, San Francisco, CA 94103",
        )
        db.add(org)
        db.flush()
        logger.info("seeded organization", extra={"slug": org.slug})
    return org


def upsert_user(
    db: Session,
    email: str,
    first: str,
    last: str,
    *,
    phone: str | None = None,
    with_password: bool = False,
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            auth_provider_id=f"dev|{email}",
            email=email,
            first_name=first,
            last_name=last,
            phone=phone,
            password_hash=hash_password(DEMO_PASSWORD) if with_password else None,
        )
        db.add(user)
        db.flush()
    return user


def upsert_membership(db: Session, org: Organization, user: User, role: Role) -> None:
    existing = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.role == role,
        )
    )
    if existing is None:
        db.add(
            OrganizationMembership(
                organization_id=org.id,
                user_id=user.id,
                role=role,
                status=MembershipStatus.ACTIVE,
            )
        )
        db.flush()


def seed_services(db: Session, org: Organization) -> dict[str, Service]:
    catalog: dict[str, Service] = {}
    for spec in SERVICES:
        name = spec["name"]
        service = db.scalar(
            select(Service).where(Service.organization_id == org.id, Service.name == name)
        )
        if service is None:
            service = Service(
                organization_id=org.id,
                name=name,
                description=spec["description"],
                base_price=spec["base_price"],
                duration_minutes=spec["duration_minutes"],
            )
            db.add(service)
            db.flush()
        catalog[name] = service
    return catalog


def seed_employees(db: Session, org: Organization, catalog: dict[str, Service]) -> list[Employee]:
    roster: list[Employee] = []
    for spec in EMPLOYEES:
        email = spec["email"]
        # The demo employee login already exists with a password; the rest do not.
        user = upsert_user(
            db,
            email,
            spec["first_name"],
            spec["last_name"],
            with_password=email == "employee@serviceflow.demo",
        )
        upsert_membership(db, org, user, Role.EMPLOYEE)

        employee = db.scalar(
            select(Employee).where(Employee.organization_id == org.id, Employee.user_id == user.id)
        )
        if employee is None:
            employee = Employee(
                organization_id=org.id, user_id=user.id, job_title=spec["job_title"]
            )
            db.add(employee)
            db.flush()
        employee.services = [catalog[name] for name in spec["services"]]
        roster.append(employee)
    return roster


def seed_customers(db: Session, org: Organization, rng: random.Random) -> list[Customer]:
    """Top the organization up to CUSTOMER_COUNT, demo customer included."""
    records: list[Customer] = []

    demo_user = db.scalar(select(User).where(User.email == "customer@serviceflow.demo"))
    if demo_user is not None:
        records.append(upsert_customer(db, org, demo_user, notes="Demo account."))

    def total() -> int:
        return (
            db.scalar(
                select(func.count()).select_from(Customer).where(Customer.organization_id == org.id)
            )
            or 0
        )

    used_emails: set[str] = set()
    attempts = 0
    while total() < CUSTOMER_COUNT and attempts < CUSTOMER_COUNT * 4:
        attempts += 1
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        email = f"{first}.{last}{attempts}@example.com".lower()
        if email in used_emails:
            continue
        used_emails.add(email)

        phone = f"+1 (415) 555-{rng.randint(1000, 9999)}"
        user = upsert_user(db, email, first, last, phone=phone)
        upsert_membership(db, org, user, Role.CUSTOMER)
        records.append(upsert_customer(db, org, user, notes=rng.choice(CUSTOMER_NOTES)))

    return records


def upsert_customer(
    db: Session, org: Organization, user: User, *, notes: str | None = None
) -> Customer:
    customer = db.scalar(
        select(Customer).where(Customer.organization_id == org.id, Customer.user_id == user.id)
    )
    if customer is None:
        customer = Customer(organization_id=org.id, user_id=user.id, notes=notes)
        db.add(customer)
        db.flush()
    return customer


def seed_vehicles(db: Session, org: Organization, rng: random.Random) -> int:
    existing = (
        db.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.organization_id == org.id)
        )
        or 0
    )
    if existing >= VEHICLE_COUNT:
        return 0

    customers = list(
        db.scalars(
            select(Customer)
            .where(Customer.organization_id == org.id)
            # By email, not by id: ids are fresh UUIDs on every rebuild, so
            # ordering by them would hand rng.choice a differently ordered list
            # and the fixed seed would produce a different demo each time.
            .join(Customer.user)
            .order_by(User.email)
        )
    )
    if not customers:
        return 0

    # The demo customer gets two vehicles so their dashboard is not a single row.
    demo_customer = next(
        (c for c in customers if c.user.email == "customer@serviceflow.demo"), None
    )

    created = 0
    targets = ([demo_customer, demo_customer] if demo_customer else []) + [
        rng.choice(customers) for _ in range(VEHICLE_COUNT)
    ]
    for customer in targets:
        if existing + created >= VEHICLE_COUNT or customer is None:
            continue
        make, model = rng.choice(VEHICLE_MODELS)
        plate = "".join(rng.choices(string.ascii_uppercase, k=3)) + str(rng.randint(100, 999))
        db.add(
            Vehicle(
                organization_id=org.id,
                customer_id=customer.id,
                year=rng.randint(2015, 2026),
                make=make,
                model=model,
                color=rng.choice(COLORS),
                license_plate=plate,
                notes=None,
            )
        )
        created += 1
    db.flush()
    return created


def seed(db: Session) -> None:
    rng = random.Random(SEED)
    org = upsert_organization(db)

    for email, first, last, role in DEMO_USERS:
        user = upsert_user(db, email, first, last, with_password=True)
        upsert_membership(db, org, user, role)

    catalog = seed_services(db, org)
    roster = seed_employees(db, org, catalog)
    customers = seed_customers(db, org, rng)
    vehicles = seed_vehicles(db, org, rng)
    # Availability has to exist before bookings, which schedule around it.
    schedules = seed_availability(db, org)
    workload = seed_bookings(db, org, rng)
    content = seed_job_content(db, org, rng)
    alerts = seed_notifications(db, org)
    # Last: it reconstructs the trail from everything above.
    trail = seed_audit_trail(db, org, rng)

    logger.info(
        "seed complete",
        extra={
            "services": len(catalog),
            "employees": len(roster),
            "customers_touched": len(customers),
            "vehicles_created": vehicles,
            "availability_windows": schedules["availability_windows"],
            "overrides": schedules["overrides"],
            "bookings_created": workload["bookings"],
            "jobs_created": workload["jobs"],
            "notes": content["notes"],
            "photos": content["photos"],
            "notifications": alerts,
            "audit_entries": trail,
        },
    )


def main() -> None:
    configure_logging()
    from serviceflow.db.session import session_scope

    with session_scope() as db:
        seed(db)
        totals = {
            "services": db.scalar(select(func.count()).select_from(Service)),
            "employees": db.scalar(select(func.count()).select_from(Employee)),
            "customers": db.scalar(select(func.count()).select_from(Customer)),
            "vehicles": db.scalar(select(func.count()).select_from(Vehicle)),
            "bookings": db.scalar(select(func.count()).select_from(Booking)),
            "jobs": db.scalar(select(func.count()).select_from(Job)),
            "completed_jobs": db.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.COMPLETED)
            ),
            "availability": db.scalar(select(func.count()).select_from(EmployeeAvailability)),
            "overrides": db.scalar(select(func.count()).select_from(AvailabilityOverride)),
            "notes": db.scalar(select(func.count()).select_from(JobNote)),
            "photos": db.scalar(select(func.count()).select_from(JobPhoto)),
            "notifications": db.scalar(select(func.count()).select_from(Notification)),
            "audit_entries": db.scalar(select(func.count()).select_from(AuditLog)),
        }

    print(f"Seed complete. Demo logins (password: {DEMO_PASSWORD}):")
    for email, _, _, role in DEMO_USERS:
        print(f"  {role.value:<9} {email}")
    print("Totals: " + ", ".join(f"{k}={v}" for k, v in totals.items()))


if __name__ == "__main__":
    main()
