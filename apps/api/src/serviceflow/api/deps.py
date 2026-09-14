"""Request dependencies: database session, caller identity, tenant scope, permission guards.

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

from serviceflow.auth.permissions import Permission
from serviceflow.auth.principal import AuthenticatedUser, CurrentUser
from serviceflow.auth.provider import AuthProvider
from serviceflow.core.config import Settings, get_settings
from serviceflow.core.context import bind_actor
from serviceflow.core.errors import InvalidRole, TenantAccessDenied, Unauthorized
from serviceflow.db.models.enums import MembershipStatus
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.user import User
from serviceflow.db.session import get_session_factory
from serviceflow.db.tenancy import bind_tenant
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


def _verified_user(db: Session, provider: AuthProvider, authorization: str | None) -> User:
    principal = provider.verify_token(_bearer_token(authorization))
    user = db.scalar(select(User).where(User.auth_provider_id == principal.auth_provider_id))
    if user is None:
        raise Unauthorized()
    return user


def get_authenticated_user(
    db: DbSession,
    provider: Annotated[AuthProvider, Depends(get_auth_provider)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """A verified caller, before any tenant is chosen.

    Enough for the session lookup and for platform administration. Tenant-owned
    routes use `get_current_user`, which also resolves and binds the tenant.
    """
    user = _verified_user(db, provider, authorization)
    bind_actor(str(user.id), "")
    return AuthenticatedUser(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_platform_admin=user.is_platform_admin,
    )


def get_current_user(
    db: DbSession,
    provider: Annotated[AuthProvider, Depends(get_auth_provider)],
    authorization: Annotated[str | None, Header()] = None,
    x_organization_id: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    principal = provider.verify_token(_bearer_token(authorization))
    # The user and their active memberships in one round trip: this runs on
    # every authenticated request, so it is worth not paying for twice.
    rows = db.execute(
        select(User, OrganizationMembership)
        .outerjoin(
            OrganizationMembership,
            (OrganizationMembership.user_id == User.id)
            & (OrganizationMembership.status == MembershipStatus.ACTIVE),
        )
        .where(User.auth_provider_id == principal.auth_provider_id)
    ).all()
    if not rows:
        raise Unauthorized()
    user = rows[0][0]
    memberships = [membership for _, membership in rows if membership is not None]
    if not memberships:
        if user.is_platform_admin:
            # Operating the platform is not the same as reading a tenant's
            # customers. A platform admin gets tenant data only by being given a
            # membership in that tenant, which is visible and audited.
            raise TenantAccessDenied("Platform administrators don't have access to tenant records.")
        raise TenantAccessDenied("Your account isn't a member of any organization yet.")

    if x_organization_id:
        try:
            requested_org = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise TenantAccessDenied() from exc
        scoped = [m for m in memberships if m.organization_id == requested_org]
        if not scoped:
            # Same response whether the org is missing or simply not theirs, so the
            # header can't be used to probe for organizations that exist.
            raise TenantAccessDenied()
    else:
        organization_ids = {m.organization_id for m in memberships}
        if len(organization_ids) > 1:
            raise TenantAccessDenied("Choose an organization for this request.")
        scoped = memberships

    organization_id = scoped[0].organization_id
    bind_actor(str(user.id), str(organization_id))
    # From here on, PostgreSQL row level security confines every statement on
    # this session to the caller's organization (db/tenancy.py).
    bind_tenant(db, organization_id)

    return CurrentUser(
        user_id=user.id,
        organization_id=organization_id,
        email=user.email,
        full_name=user.full_name,
        roles=frozenset(m.role for m in scoped),
        is_platform_admin=user.is_platform_admin,
    )


ActiveUser = Annotated[CurrentUser, Depends(get_current_user)]
SignedInUser = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]


def require_permission(*permissions: Permission) -> Callable[[CurrentUser], CurrentUser]:
    """Guard a route so only callers holding at least one of `permissions` reach it.

    A guard, not the whole decision: the service layer still narrows "own"
    permissions to the caller's own records.
    """

    def _guard(current_user: ActiveUser) -> CurrentUser:
        if not current_user.can(*permissions):
            raise InvalidRole()
        return current_user

    return _guard


def require_platform_admin(user: SignedInUser) -> AuthenticatedUser:
    if not user.is_platform_admin:
        raise InvalidRole()
    return user


P = Permission

PlatformAdmin = Annotated[AuthenticatedUser, Depends(require_platform_admin)]
OrganizationManager = Annotated[CurrentUser, Depends(require_permission(P.ORGANIZATION_MANAGE))]
MembersReader = Annotated[CurrentUser, Depends(require_permission(P.MEMBERS_READ))]
MembersManager = Annotated[CurrentUser, Depends(require_permission(P.MEMBERS_MANAGE))]
CustomersReader = Annotated[CurrentUser, Depends(require_permission(P.CUSTOMERS_READ))]
CustomersWriter = Annotated[CurrentUser, Depends(require_permission(P.CUSTOMERS_WRITE))]
CustomersArchiver = Annotated[CurrentUser, Depends(require_permission(P.CUSTOMERS_ARCHIVE))]
EmployeesReader = Annotated[CurrentUser, Depends(require_permission(P.EMPLOYEES_READ))]
EmployeesWriter = Annotated[CurrentUser, Depends(require_permission(P.EMPLOYEES_WRITE))]
ServicesWriter = Annotated[CurrentUser, Depends(require_permission(P.SERVICES_WRITE))]
AvailabilityUser = Annotated[
    CurrentUser, Depends(require_permission(P.AVAILABILITY_MANAGE, P.AVAILABILITY_OWN))
]
BookingsUser = Annotated[
    CurrentUser, Depends(require_permission(P.BOOKINGS_READ, P.BOOKINGS_WRITE, P.BOOKINGS_OWN))
]
BookingsCreator = Annotated[
    CurrentUser, Depends(require_permission(P.BOOKINGS_WRITE, P.BOOKINGS_OWN))
]
BookingsWriter = Annotated[CurrentUser, Depends(require_permission(P.BOOKINGS_WRITE))]
JobsUser = Annotated[
    CurrentUser, Depends(require_permission(P.JOBS_READ, P.JOBS_DISPATCH, P.JOBS_WORK))
]
JobsWorker = Annotated[CurrentUser, Depends(require_permission(P.JOBS_DISPATCH, P.JOBS_WORK))]
JobsDispatcher = Annotated[CurrentUser, Depends(require_permission(P.JOBS_DISPATCH))]
ScheduleUser = Annotated[CurrentUser, Depends(require_permission(P.SCHEDULE_READ, P.SCHEDULE_OWN))]
AuditReader = Annotated[CurrentUser, Depends(require_permission(P.AUDIT_READ))]
Searcher = Annotated[CurrentUser, Depends(require_permission(P.SEARCH))]
InfrastructureReader = Annotated[CurrentUser, Depends(require_permission(P.INFRASTRUCTURE_READ))]
DashboardReader = Annotated[CurrentUser, Depends(require_permission(P.DASHBOARD_READ))]


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
