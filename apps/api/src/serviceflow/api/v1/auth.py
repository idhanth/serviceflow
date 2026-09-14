"""Sign-in for the dev auth provider, plus the session lookup used by every client.

When AUTH_PROVIDER=clerk the login route is not mounted: Clerk owns the credential
exchange and the frontend sends its session token straight to /auth/me.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from serviceflow.api.deps import DbSession, SignedInUser, rate_limit
from serviceflow.auth.passwords import verify_password
from serviceflow.auth.permissions import PLATFORM_ADMIN_PERMISSIONS, permissions_for
from serviceflow.auth.provider import DevJWTAuthProvider
from serviceflow.core.config import get_settings
from serviceflow.core.errors import Unauthorized
from serviceflow.db.models.enums import MembershipStatus
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.user import User
from serviceflow.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MembershipSummary,
    SessionUser,
    SignupRequest,
)
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services import signup as signup_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _session_user(user: User) -> SessionUser:
    return SessionUser(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        is_platform_admin=user.is_platform_admin,
        platform_permissions=sorted(PLATFORM_ADMIN_PERMISSIONS) if user.is_platform_admin else [],
        memberships=[
            MembershipSummary(
                organization_id=m.organization_id,
                organization_name=m.organization.name,
                organization_slug=m.organization.slug,
                role=m.role,
                permissions=sorted(permissions_for([m.role])),
            )
            for m in user.memberships
            if m.status is MembershipStatus.ACTIVE
        ],
    )


def _load_user_with_memberships(
    db: Session, *, email: str | None = None, user_id: uuid.UUID | None = None
) -> User | None:
    stmt = select(User).options(
        selectinload(User.memberships).selectinload(OrganizationMembership.organization)
    )
    stmt = stmt.where(User.email == email) if email is not None else stmt.where(User.id == user_id)
    return db.scalar(stmt)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Sign in (dev provider only)",
    dependencies=[Depends(rate_limit("login"))],
)
def login(payload: LoginRequest, request: Request, db: DbSession) -> LoginResponse:
    provider = request.app.state.auth_provider
    if not isinstance(provider, DevJWTAuthProvider):
        raise Unauthorized("Sign-in is handled by the configured identity provider.")

    user = _load_user_with_memberships(db, email=payload.email.lower())
    # Same message for unknown email and wrong password: no account enumeration.
    if user is None or not verify_password(payload.password, user.password_hash):
        logger.info("login rejected", extra={"email_domain": payload.email.split("@")[-1]})
        raise Unauthorized("That email and password combination didn't match.")

    settings = get_settings()
    token = provider.issue_token(user.auth_provider_id, email=user.email)
    return LoginResponse(
        access_token=token,
        expires_in=settings.access_token_ttl_seconds,
        user=_session_user(user),
    )


@router.get("/me", response_model=DataResponse[SessionUser], summary="Current session")
def me(current_user: SignedInUser, db: DbSession) -> DataResponse[SessionUser]:
    """Who is signed in, their memberships, and what each membership may do.

    Works before a tenant is chosen, so a platform administrator - who holds no
    membership - can load their session too.
    """
    user = _load_user_with_memberships(db, user_id=current_user.user_id)
    if user is None:
        raise Unauthorized()
    return DataResponse[SessionUser](data=_session_user(user))


@router.post(
    "/signup",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer account (dev provider only)",
    dependencies=[Depends(rate_limit("signup"))],
)
def signup(payload: SignupRequest, request: Request, db: DbSession) -> LoginResponse:
    """Registers a customer and signs them straight in. Rate limited by address."""
    provider = request.app.state.auth_provider
    if not isinstance(provider, DevJWTAuthProvider):
        raise Unauthorized("Sign-up is handled by the configured identity provider.")

    user, _organization = signup_service.sign_up_customer(
        db,
        organization_slug=payload.organization_slug,
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
    )

    loaded = _load_user_with_memberships(db, user_id=user.id)
    if loaded is None:  # pragma: no cover - the row was just committed
        raise Unauthorized()

    settings = get_settings()
    return LoginResponse(
        access_token=provider.issue_token(loaded.auth_provider_id, email=loaded.email),
        expires_in=settings.access_token_ttl_seconds,
        user=_session_user(loaded),
    )


me_router = APIRouter(tags=["auth"])


@me_router.get("/me", response_model=DataResponse[SessionUser], summary="Current session")
def me_alias(current_user: SignedInUser, db: DbSession) -> DataResponse[SessionUser]:
    """Same as /auth/me."""
    return me(current_user, db)
