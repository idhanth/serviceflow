"""Idempotent development seed.

Phase 1 seeds the organization and the three demo logins from PRD 50. Later
phases extend this with services, employees, customers, vehicles and bookings.
Running it twice must not duplicate anything.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.auth.passwords import hash_password
from serviceflow.core.logging import configure_logging
from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User
from serviceflow.db.session import session_scope

logger = logging.getLogger(__name__)

DEMO_ORG_SLUG = "gleam-auto-detailing"
DEMO_PASSWORD = "demo1234"

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


def upsert_user(db: Session, email: str, first: str, last: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            auth_provider_id=f"dev|{email}",
            email=email,
            first_name=first,
            last_name=last,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        db.add(user)
        db.flush()
        logger.info("seeded user", extra={"email": email})
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


def seed(db: Session) -> None:
    org = upsert_organization(db)
    for email, first, last, role in DEMO_USERS:
        user = upsert_user(db, email, first, last)
        upsert_membership(db, org, user, role)


def main() -> None:
    configure_logging()
    with session_scope() as db:
        seed(db)
    print(f"Seed complete. Demo logins (password: {DEMO_PASSWORD}):")
    for email, _, _, role in DEMO_USERS:
        print(f"  {role.value:<9} {email}")


if __name__ == "__main__":
    main()
