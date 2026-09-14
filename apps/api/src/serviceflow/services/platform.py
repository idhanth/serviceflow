"""Platform administration: the tenants themselves, not what is inside them.

A platform admin can list businesses with their sizes and create a new business
with its first owner. They cannot open a tenant's customers, bookings or jobs:
those routes require a membership in the tenant, and platform administration is
deliberately not one.

The counts below are the one place a request reads across tenants, so this
module is also the one request path that lifts row level security - and it only
ever selects aggregate counts.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from serviceflow.core.errors import ValidationFailed
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, MembershipStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.tenancy import allow_cross_tenant, bind_tenant
from serviceflow.schemas.admin import TenantCreate, TenantSummary
from serviceflow.services import audit
from serviceflow.services.people import find_or_create_user


def _counts(
    db: Session, model: type, column: InstrumentedAttribute[uuid.UUID]
) -> dict[uuid.UUID, int]:
    rows = db.execute(select(column, func.count()).select_from(model).group_by(column)).all()
    return {row[0]: int(row[1]) for row in rows}


def list_tenants(db: Session) -> list[TenantSummary]:
    allow_cross_tenant(db)
    members = _counts(db, OrganizationMembership, OrganizationMembership.organization_id)
    customers = _counts(db, Customer, Customer.organization_id)
    employees = _counts(db, Employee, Employee.organization_id)
    bookings = _counts(db, Booking, Booking.organization_id)
    jobs = _counts(db, Job, Job.organization_id)
    organizations = db.scalars(select(Organization).order_by(Organization.name, Organization.id))
    return [
        TenantSummary(
            id=org.id,
            name=org.name,
            slug=org.slug,
            timezone=org.timezone,
            created_at=org.created_at,
            members=members.get(org.id, 0),
            customers=customers.get(org.id, 0),
            employees=employees.get(org.id, 0),
            bookings=bookings.get(org.id, 0),
            jobs=jobs.get(org.id, 0),
        )
        for org in organizations
    ]


def create_tenant(db: Session, payload: TenantCreate, *, actor_user_id: uuid.UUID) -> Organization:
    if db.scalar(select(Organization.id).where(Organization.slug == payload.slug)) is not None:
        raise ValidationFailed(
            "That address is already taken.", details={"fields": {"slug": "Already in use."}}
        )
    organization = Organization(
        name=payload.name.strip(),
        slug=payload.slug,
        email=str(payload.email),
        timezone=payload.timezone,
    )
    db.add(organization)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationFailed(
            "That address is already taken.", details={"fields": {"slug": "Already in use."}}
        ) from exc

    # Everything below belongs to the new tenant, and row level security holds it there.
    bind_tenant(db, organization.id)
    owner = find_or_create_user(
        db,
        email=str(payload.owner_email),
        first_name=payload.owner_first_name,
        last_name=payload.owner_last_name,
    )
    db.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=owner.id,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    audit.record(
        db,
        organization_id=organization.id,
        actor_user_id=actor_user_id,
        action=AuditAction.TENANT_CREATED,
        resource_type="organization",
        resource_id=organization.id,
        metadata={"name": organization.name, "owner": owner.full_name},
    )
    db.commit()
    db.refresh(organization)
    return organization
