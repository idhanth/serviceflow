"""Customer self-signup.

The PRD's end-to-end flow (62) begins with a customer signing up, so this is the
minimum needed to reach a bookable account: create the person, their customer
record and an active CUSTOMER membership in one organization.

Deliberately *not* built here: invitations, email verification and claiming a
staff-created account. Those need the email infrastructure that arrives in phase
6; see docs/adr-0003.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from serviceflow.auth.passwords import hash_password
from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User
from serviceflow.services.people import ensure_membership

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8

# One message for every "we can't create this" case, so signup cannot be used to
# test whether an address already has an account.
_TAKEN_MESSAGE = (
    "We couldn't create an account with that email. If you already have one, sign in instead."
)


def sign_up_customer(
    db: Session,
    *,
    organization_slug: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
) -> tuple[User, Organization]:
    organization = db.scalar(
        select(Organization).where(Organization.slug == organization_slug.strip().lower())
    )
    if organization is None:
        raise NotFound("We couldn't find that business.")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(
            "Choose a longer password.",
            details={"fields": {"password": f"Use at least {MIN_PASSWORD_LENGTH} characters."}},
        )

    normalized = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized)) is not None:
        logger.info("signup rejected: email already registered")
        raise ValidationFailed(_TAKEN_MESSAGE, details={"fields": {"email": "Unavailable."}})

    user = User(
        auth_provider_id=f"dev|{normalized}",
        email=normalized,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone,
        password_hash=hash_password(password),
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError as exc:
        # Lost a race against a concurrent signup for the same address.
        db.rollback()
        raise ValidationFailed(
            _TAKEN_MESSAGE, details={"fields": {"email": "Unavailable."}}
        ) from exc

    ensure_membership(db, organization_id=organization.id, user_id=user.id, role=Role.CUSTOMER)
    db.add(Customer(organization_id=organization.id, user_id=user.id))
    db.commit()
    db.refresh(user)

    logger.info("customer signed up", extra={"organization_id": str(organization.id)})
    return user, organization
