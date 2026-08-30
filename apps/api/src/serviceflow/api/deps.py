"""Request dependencies: database session, caller identity, tenant scope, role guards.

Every organization-owned query downstream takes its organization_id from
CurrentUser, which is only ever built from a verified active membership. Nothing
reads a tenant id straight off the request body (PRD 5, 61).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.auth.principal import CurrentUser
from serviceflow.auth.provider import AuthProvider
from serviceflow.core.config import Settings, get_settings
from serviceflow.core.context import bind_actor
from serviceflow.core.errors import Forbidden, Unauthorized
from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.user import User
from serviceflow.db.session import get_session_factory
from serviceflow.services import ratelimit


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_auth_provider(request: Request) -> AuthProvider:
    provider: AuthProvider = request.app.state.auth_provider
    return provider


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise Unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized()
    return token.strip()


def get_current_user(
    db: DbSession,
    provider: Annotated[AuthProvider, Depends(get_auth_provider)],
    authorization: Annotated[str | None, Header()] = None,
    x_organization_id: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    principal = provider.verify_token(_bearer_token(authorization))

    user = db.scalar(select(User).where(User.auth_provider_id == principal.auth_provider_id))
    if user is None:
        raise Unauthorized()

    memberships = list(
        db.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.status == MembershipStatus.ACTIVE,
            )
        )
    )
    if not memberships:
        raise Forbidden("Your account isn't a member of any organization yet.")

    if x_organization_id:
        try:
            requested_org = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise Forbidden("That organization isn't available to you.") from exc
        scoped = [m for m in memberships if m.organization_id == requested_org]
        if not scoped:
            # Same response whether the org is missing or simply not theirs, so the
            # header can't be used to probe for organizations that exist.
            raise Forbidden("That organization isn't available to you.")
    else:
        organization_ids = {m.organization_id for m in memberships}
        if len(organization_ids) > 1:
            raise Forbidden("Choose an organization for this request.")
        scoped = memberships

    organization_id = scoped[0].organization_id
    bind_actor(str(user.id), str(organization_id))

    return CurrentUser(
        user_id=user.id,
        organization_id=organization_id,
        email=user.email,
        full_name=user.full_name,
        roles=frozenset(m.role for m in scoped),
    )


ActiveUser = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Guard a route so only the listed organization roles may call it."""

    def _guard(current_user: ActiveUser) -> CurrentUser:
        if not current_user.has_role(*roles):
            raise Forbidden()
        return current_user

    return _guard


AdminUser = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
EmployeeUser = Annotated[CurrentUser, Depends(require_roles(Role.EMPLOYEE, Role.ADMIN))]


# ------------------------------------------------------------------ rate limiting


def client_identity(request: Request) -> str:
    """Who to count an unauthenticated request against.

    `X-Forwarded-For` is only consulted when the deployment declares how many
    proxies it has, and then only the hop that many places from the right - the
    entries beyond that are supplied by the caller and cannot be trusted. With
    no declared proxies the direct peer address is used.
    """
    settings = get_settings()
    hops = settings.trusted_proxy_count
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            return f"ip:{chain[-hops]}"

    peer = request.client.host if request.client else "unknown"
    return f"ip:{peer}"


def rate_limit(limit_name: str) -> Callable[[Request], None]:
    """Limit an unauthenticated endpoint by source address."""

    def _guard(request: Request) -> None:
        if not get_settings().rate_limiting_enabled:
            return
        ratelimit.enforce(limit_name, client_identity(request))

    return _guard


def rate_limit_user(limit_name: str) -> Callable[[CurrentUser], None]:
    """Limit an authenticated endpoint by organization and user.

    Scoping by both means one tenant cannot exhaust another's quota, and two
    users in the same organization do not consume each other's.
    """

    def _guard(current_user: ActiveUser) -> None:
        if not get_settings().rate_limiting_enabled:
            return
        ratelimit.enforce(
            limit_name, f"org:{current_user.organization_id}:user:{current_user.user_id}"
        )

    return _guard
