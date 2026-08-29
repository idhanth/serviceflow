"""Shared logic for records that hang off a User (customers and employees)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.user import User


def find_or_create_user(
    db: Session,
    *,
    email: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
) -> User:
    """Resolve a User by email, creating one if this is a new person.

    Identity is global while membership is per-organization, so one person can be
    a customer of several shops. An existing user's own details are never
    overwritten by another organization's admin.

    The new user has no password: staff-created accounts cannot sign in until
    credentials are set. Invitations are not part of this phase.
    """
    normalized = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized))
    if user is not None:
        return user

    user = User(
        auth_provider_id=f"dev|{normalized}",
        email=normalized,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone,
        password_hash=None,
    )
    db.add(user)
    db.flush()
    return user


def ensure_membership(
    db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.role == role,
        )
    )
    if membership is None:
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.flush()
    return membership


def set_membership_status(
    db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: Role, active: bool
) -> None:
    """Mirror an employee's active flag onto their membership.

    A deactivated employee must lose API access, not merely be hidden from lists
    (PRD 6, 53).
    """
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.role == role,
        )
    )
    if membership is not None:
        membership.status = MembershipStatus.ACTIVE if active else MembershipStatus.SUSPENDED
