"""Idempotent development seed: three home-service businesses and their history.

Running it repeatedly must not duplicate anything, so every step is an upsert
keyed on a natural identifier, and each business's bookings are generated only
once. It writes synthetic demo records into whatever database it is given, so
nothing runs it automatically: `python -m serviceflow.db.seed` is a deliberate act.

Demo accounts (local demo only; password `demo1234`):

    admin@serviceflow.demo           Platform Admin
    owner@serviceflow.demo           Business Owner     Northside Home Services
    manager@serviceflow.demo         Business Manager   Northside Home Services
    dispatcher@serviceflow.demo      Dispatcher         Northside Home Services
    employee@serviceflow.demo        Technician         Northside Home Services (Alex Morgan)
    customer@serviceflow.demo        Customer           Northside Home Services (Sarah Mitchell)
    analyst@serviceflow.demo         Read-only Analyst  Northside Home Services
    harbor.owner@serviceflow.demo    Business Owner     Harbor Plumbing & Heating
"""

from __future__ import annotations

import logging
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.auth.passwords import hash_password
from serviceflow.core.logging import configure_logging
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import JobStatus, MembershipStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.seed_audit import seed_audit_trail
from serviceflow.db.seed_availability import seed_availability
from serviceflow.db.seed_bookings import seed_bookings
from serviceflow.db.seed_content import seed_job_content, seed_notifications
from serviceflow.db.seed_data import (
    CUSTOMER_NOTES,
    DEMO_PASSWORD,
    FIRST_NAMES,
    LAST_NAMES,
    PLATFORM_ADMIN,
    STREETS,
    TENANTS,
    TenantSpec,
)
from serviceflow.services.employees import set_qualifications

logger = logging.getLogger(__name__)

SEED = 20260914  # fixed so reseeding a fresh database reproduces the same demo


def upsert_organization(db: Session, spec: TenantSpec) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == spec["slug"]))
    if org is None:
        org = Organization(
            name=spec["name"],
            slug=spec["slug"],
            email=spec["email"],
            phone=spec["phone"],
            timezone=spec["timezone"],
            address=spec["address"],
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


def seed_services(db: Session, org: Organization, spec: TenantSpec) -> dict[str, Service]:
    catalog: dict[str, Service] = {}
    for service_spec in spec["services"]:
        name = service_spec["name"]
        service = db.scalar(
            select(Service).where(Service.organization_id == org.id, Service.name == name)
        )
        if service is None:
            service = Service(
                organization_id=org.id,
                name=name,
                description=service_spec["description"],
                base_price=service_spec["base_price"],
                duration_minutes=service_spec["duration_minutes"],
            )
            db.add(service)
            db.flush()
        catalog[name] = service
    return catalog


def seed_employees(
    db: Session, org: Organization, spec: TenantSpec, catalog: dict[str, Service]
) -> list[Employee]:
    roster: list[Employee] = []
    for employee_spec in spec["employees"]:
        user = upsert_user(
            db,
            employee_spec["email"],
            employee_spec["first_name"],
            employee_spec["last_name"],
            with_password=employee_spec["can_sign_in"],
        )
        upsert_membership(db, org, user, Role.TECHNICIAN)
        employee = db.scalar(
            select(Employee).where(Employee.organization_id == org.id, Employee.user_id == user.id)
        )
        if employee is None:
            employee = Employee(
                organization_id=org.id, user_id=user.id, job_title=employee_spec["job_title"]
            )
            db.add(employee)
            db.flush()
        set_qualifications(employee, [catalog[name] for name in employee_spec["services"]])
        db.flush()
        roster.append(employee)
    return roster


def upsert_customer(
    db: Session, org: Organization, user: User, *, address: str, notes: str | None
) -> Customer:
    customer = db.scalar(
        select(Customer).where(Customer.organization_id == org.id, Customer.user_id == user.id)
    )
    if customer is None:
        customer = Customer(organization_id=org.id, user_id=user.id, address=address, notes=notes)
        db.add(customer)
        db.flush()
    return customer


def seed_customers(
    db: Session, org: Organization, spec: TenantSpec, rng: random.Random
) -> list[Customer]:
    """The named customers first, then realistic strangers up to the target count."""
    records: list[Customer] = []
    for named in spec["named_customers"]:
        user = upsert_user(
            db,
            named["email"],
            named["first_name"],
            named["last_name"],
            phone=named["phone"],
            with_password=named["can_sign_in"],
        )
        upsert_membership(db, org, user, Role.CUSTOMER)
        records.append(
            upsert_customer(db, org, user, address=named["address"], notes=named["notes"])
        )

    def total() -> int:
        return (
            db.scalar(
                select(func.count()).select_from(Customer).where(Customer.organization_id == org.id)
            )
            or 0
        )

    domain = spec["slug"].split("-")[0]
    attempt = 0
    while total() < spec["customer_count"] and attempt < spec["customer_count"] * 4:
        attempt += 1
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = f"{first}.{last}.{domain}{attempt}@example.com".lower()
        phone = f"+1 ({spec['area_code']}) 555-{rng.randint(1000, 9999)}"
        address = f"{rng.randint(100, 4999)} {rng.choice(STREETS)}, {rng.choice(spec['cities'])}"
        user = upsert_user(db, email, first, last, phone=phone)
        upsert_membership(db, org, user, Role.CUSTOMER)
        records.append(
            upsert_customer(db, org, user, address=address, notes=rng.choice(CUSTOMER_NOTES))
        )
    return records


def seed(db: Session) -> dict[str, dict[str, int]]:
    rng = random.Random(SEED)

    admin = upsert_user(
        db,
        PLATFORM_ADMIN["email"],
        PLATFORM_ADMIN["first_name"],
        PLATFORM_ADMIN["last_name"],
        with_password=True,
    )
    admin.is_platform_admin = True

    report: dict[str, dict[str, int]] = {}
    for spec in TENANTS:
        org = upsert_organization(db, spec)
        for account in spec["accounts"]:
            user = upsert_user(
                db,
                account["email"],
                account["first_name"],
                account["last_name"],
                with_password=True,
            )
            upsert_membership(db, org, user, account["role"])

        catalog = seed_services(db, org, spec)
        roster = seed_employees(db, org, spec, catalog)
        customers = seed_customers(db, org, spec, rng)
        # Availability has to exist before bookings, which schedule around it.
        schedules = seed_availability(db, org)
        workload = seed_bookings(db, org, spec, rng)
        content = seed_job_content(db, org, spec, rng)
        alerts = seed_notifications(db, org)
        # Last: it reconstructs the trail from everything above.
        trail = seed_audit_trail(db, org, rng)

        report[spec["slug"]] = {
            "services": len(catalog),
            "employees": len(roster),
            "customers": len(customers),
            **schedules,
            **workload,
            **content,
            "notifications": alerts,
            "audit_entries": trail,
        }
        logger.info("seeded tenant", extra={"slug": spec["slug"], **report[spec["slug"]]})
    return report


def main() -> None:
    configure_logging()
    from serviceflow.db.session import session_scope

    with session_scope() as db:
        seed(db)
        totals = {
            "tenants": db.scalar(select(func.count()).select_from(Organization)),
            "services": db.scalar(select(func.count()).select_from(Service)),
            "employees": db.scalar(select(func.count()).select_from(Employee)),
            "customers": db.scalar(select(func.count()).select_from(Customer)),
            "bookings": db.scalar(select(func.count()).select_from(Booking)),
            "jobs": db.scalar(select(func.count()).select_from(Job)),
            "completed_jobs": db.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.COMPLETED)
            ),
            "notifications": db.scalar(select(func.count()).select_from(Notification)),
            "audit_entries": db.scalar(select(func.count()).select_from(AuditLog)),
        }

    print(f"Seed complete. Demo logins for local development only (password: {DEMO_PASSWORD}):")
    print(f"  {'PLATFORM_ADMIN':<15} {PLATFORM_ADMIN['email']}")
    for spec in TENANTS:
        for account in spec["accounts"]:
            print(f"  {account['role'].value:<15} {account['email']:<36} {spec['name']}")
        for employee in spec["employees"]:
            if employee["can_sign_in"]:
                print(f"  {'TECHNICIAN':<15} {employee['email']:<36} {spec['name']}")
        for named in spec["named_customers"]:
            if named["can_sign_in"]:
                print(f"  {'CUSTOMER':<15} {named['email']:<36} {spec['name']}")
    print("Totals: " + ", ".join(f"{k}={v}" for k, v in totals.items()))


if __name__ == "__main__":
    main()
