"""Tenant members: who can sign in to a business, and with which role.

Owners add people and change roles. The rules that keep a business operable:

* nobody changes their own role or suspends themselves, so an owner can't lock
  themselves out by accident;
* the last active owner can be neither demoted nor suspended;
* a technician always has an employee record, so they can be scheduled, and a
  customer always has a customer record, so they can book.

Every change is audited: USER_INVITED, USER_ROLE_CHANGED, MEMBER_SUSPENDED,
MEMBER_REACTIVATED.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.user import User
from serviceflow.services import audit
from serviceflow.services.people import find_or_create_user
from serviceflow.services.search import like_pattern


def list_members(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    role: Role | None = None,
    q: str | None = None,
) -> Page[OrganizationMembership]:
    filters = [OrganizationMembership.organization_id == organization_id]
    if role is not None:
        filters.append(OrganizationMembership.role == role)
    if q:
        pattern = like_pattern(q)
        filters.append(
            OrganizationMembership.user.has(
                or_(
                    User.email.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    (User.first_name + " " + User.last_name).ilike(pattern),
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(OrganizationMembership).where(*filters)) or 0
    items = list(
        db.scalars(
            select(OrganizationMembership)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(*filters)
            .options(joinedload(OrganizationMembership.user))
            .order_by(OrganizationMembership.role, User.first_name, OrganizationMembership.id)
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def _ensure_role_record(
    db: Session, organization_id: uuid.UUID, user: User, role: Role, job_title: str | None
) -> None:
    if role is Role.TECHNICIAN:
        employee = db.scalar(
            select(Employee).where(
                Employee.organization_id == organization_id, Employee.user_id == user.id
            )
        )
        if employee is None:
            db.add(
                Employee(
                    organization_id=organization_id,
                    user_id=user.id,
                    job_title=(job_title or "Technician").strip(),
                )
            )
    elif role is Role.CUSTOMER:
        customer = db.scalar(
            select(Customer).where(
                Customer.organization_id == organization_id, Customer.user_id == user.id
            )
        )
        if customer is None:
            db.add(Customer(organization_id=organization_id, user_id=user.id))


def invite_member(
    db: Session,
    organization_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    email: str,
    first_name: str,
    last_name: str,
    role: Role,
    job_title: str | None = None,
) -> OrganizationMembership:
    user = find_or_create_user(db, email=email, first_name=first_name, last_name=last_name)
    existing = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.role == role,
        )
    )
    if existing is not None:
        raise ValidationFailed(
            f"{user.full_name} already has that role here.",
            details={"fields": {"role": "Already assigned."}},
        )

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role=role,
        status=MembershipStatus.ACTIVE,
    )
    db.add(membership)
    _ensure_role_record(db, organization_id, user, role, job_title)
    db.flush()
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.USER_INVITED,
        resource_type="member",
        resource_id=membership.id,
        metadata={"name": user.full_name, "role": role.value},
    )
    db.commit()
    return _load(db, organization_id, membership.id)


def _load(
    db: Session, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .options(joinedload(OrganizationMembership.user))
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise NotFound("We couldn't find that member.")
    return membership


def _active_owner_count(db: Session, organization_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == Role.OWNER,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        or 0
    )


def update_member(
    db: Session,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    role: Role | None = None,
    status: MembershipStatus | None = None,
) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise NotFound("We couldn't find that member.")
    user = db.get(User, membership.user_id)
    if user is None:  # pragma: no cover - foreign key
        raise NotFound("We couldn't find that member.")

    role_change = role is not None and role is not membership.role
    status_change = status is not None and status is not membership.status
    if not (role_change or status_change):
        return _load(db, organization_id, membership_id)

    if membership.user_id == actor_user_id:
        raise ValidationFailed(
            "You can't change your own access. Ask another owner.",
            details={"fields": {"role": "Not for your own membership."}},
        )
    losing_owner = membership.role is Role.OWNER and (
        role_change or status is MembershipStatus.SUSPENDED
    )
    if losing_owner and _active_owner_count(db, organization_id) <= 1:
        raise ValidationFailed(
            "A business needs at least one active owner.",
            details={"fields": {"role": "This is the last owner."}},
        )

    if role_change and role is not None:
        clash = db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == membership.user_id,
                OrganizationMembership.role == role,
            )
        )
        if clash is not None:
            raise ValidationFailed(
                f"{user.full_name} already has that role here.",
                details={"fields": {"role": "Already assigned."}},
            )
        previous = membership.role
        membership.role = role
        _ensure_role_record(db, organization_id, user, role, None)
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=AuditAction.USER_ROLE_CHANGED,
            resource_type="member",
            resource_id=membership.id,
            metadata={"name": user.full_name, "from": previous.value, "to": role.value},
        )

    if status_change and status is not None:
        membership.status = status
        employee = db.scalar(
            select(Employee).where(
                Employee.organization_id == organization_id,
                Employee.user_id == membership.user_id,
            )
        )
        if employee is not None and membership.role is Role.TECHNICIAN:
            employee.active = status is MembershipStatus.ACTIVE
        audit.record(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=(
                AuditAction.MEMBER_REACTIVATED
                if status is MembershipStatus.ACTIVE
                else AuditAction.MEMBER_SUSPENDED
            ),
            resource_type="member",
            resource_id=membership.id,
            metadata={"name": user.full_name, "role": membership.role.value},
        )

    db.commit()
    return _load(db, organization_id, membership_id)
