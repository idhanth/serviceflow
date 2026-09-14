"""The permission model: what each of the seven roles may do.

Routes and services ask for a *permission*, never for a role. That keeps the
answer to "who can cancel a booking?" in exactly one table below, so adding a
role or narrowing one is a one-line change that every endpoint inherits.

The seven roles:

    Platform Admin   operates the platform: lists and creates tenants. Holds no
                     tenant membership and therefore reads no tenant's records.
    Owner            full control of their tenant, including settings and members.
    Manager          runs the business day to day: staff, customers, bookings, jobs.
    Dispatcher       schedules work: bookings, assignments, availability.
    Technician       their own assigned jobs and their own availability.
    Customer         their own bookings and service history.
    Analyst          read-only access to operational data; changes nothing.

Holding a permission is necessary but never sufficient. Tenant scope is applied
separately (every query filters by the caller's organization, and PostgreSQL row
level security backs that up), and "own" permissions are narrowed to the
caller's own records inside the service layer.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable

from serviceflow.db.models.enums import Role


class Permission(enum.StrEnum):
    ORGANIZATION_MANAGE = "organization:manage"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"

    CUSTOMERS_READ = "customers:read"
    CUSTOMERS_WRITE = "customers:write"
    CUSTOMERS_ARCHIVE = "customers:archive"

    EMPLOYEES_READ = "employees:read"
    EMPLOYEES_WRITE = "employees:write"

    SERVICES_WRITE = "services:write"
    SERVICES_READ_RETIRED = "services:read_retired"

    AVAILABILITY_MANAGE = "availability:manage"  # anyone in the tenant
    AVAILABILITY_OWN = "availability:own"  # the caller's own schedule only

    BOOKINGS_READ = "bookings:read"  # every booking in the tenant
    BOOKINGS_WRITE = "bookings:write"  # book for any customer, assign, reject, move, cancel
    BOOKINGS_OWN = "bookings:own"  # a customer's own bookings

    JOBS_READ = "jobs:read"  # every job in the tenant
    JOBS_DISPATCH = "jobs:dispatch"  # assign, reassign, cancel, move any job along
    JOBS_WORK = "jobs:work"  # start and complete jobs assigned to the caller

    SCHEDULE_READ = "schedule:read"  # the whole team's schedule
    SCHEDULE_OWN = "schedule:own"

    AUDIT_READ = "audit:read"
    SEARCH = "search"
    INFRASTRUCTURE_READ = "infrastructure:read"
    DASHBOARD_READ = "dashboard:read"

    PLATFORM_TENANTS = "platform:tenants"


P = Permission

_READ_ONLY_OPERATIONS = frozenset(
    {
        P.MEMBERS_READ,
        P.CUSTOMERS_READ,
        P.EMPLOYEES_READ,
        P.SERVICES_READ_RETIRED,
        P.BOOKINGS_READ,
        P.JOBS_READ,
        P.SCHEDULE_READ,
        P.SEARCH,
        P.DASHBOARD_READ,
    }
)

_DISPATCH = frozenset(
    {
        P.CUSTOMERS_READ,
        P.CUSTOMERS_WRITE,
        P.EMPLOYEES_READ,
        P.AVAILABILITY_MANAGE,
        P.BOOKINGS_READ,
        P.BOOKINGS_WRITE,
        P.JOBS_READ,
        P.JOBS_DISPATCH,
        P.SCHEDULE_READ,
        P.SEARCH,
        P.DASHBOARD_READ,
    }
)

_MANAGE = (
    _DISPATCH
    | _READ_ONLY_OPERATIONS
    | {
        P.CUSTOMERS_ARCHIVE,
        P.EMPLOYEES_WRITE,
        P.SERVICES_WRITE,
        P.AUDIT_READ,
        P.INFRASTRUCTURE_READ,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(_MANAGE | {P.ORGANIZATION_MANAGE, P.MEMBERS_MANAGE}),
    Role.MANAGER: frozenset(_MANAGE),
    Role.DISPATCHER: _DISPATCH,
    Role.TECHNICIAN: frozenset({P.JOBS_WORK, P.SCHEDULE_OWN, P.AVAILABILITY_OWN}),
    Role.CUSTOMER: frozenset({P.BOOKINGS_OWN}),
    Role.ANALYST: frozenset(_READ_ONLY_OPERATIONS | {P.AUDIT_READ}),
}

PLATFORM_ADMIN_PERMISSIONS: frozenset[Permission] = frozenset({P.PLATFORM_TENANTS})

# Roles an Owner may grant. Owner itself is included so a business can have
# more than one; nobody can grant platform administration through the API.
GRANTABLE_ROLES: frozenset[Role] = frozenset(Role)

# Roles whose holders are staff: they need an Employee record to be scheduled
# only when they are technicians, but all of them see internal booking detail.
STAFF_ROLES: frozenset[Role] = frozenset(
    {Role.OWNER, Role.MANAGER, Role.DISPATCHER, Role.TECHNICIAN, Role.ANALYST}
)

WRITE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        P.ORGANIZATION_MANAGE,
        P.MEMBERS_MANAGE,
        P.CUSTOMERS_WRITE,
        P.CUSTOMERS_ARCHIVE,
        P.EMPLOYEES_WRITE,
        P.SERVICES_WRITE,
        P.AVAILABILITY_MANAGE,
        P.AVAILABILITY_OWN,
        P.BOOKINGS_WRITE,
        P.BOOKINGS_OWN,
        P.JOBS_DISPATCH,
        P.JOBS_WORK,
        P.PLATFORM_TENANTS,
    }
)


def permissions_for(
    roles: Iterable[Role], *, platform_admin: bool = False
) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    if platform_admin:
        granted |= PLATFORM_ADMIN_PERMISSIONS
    return frozenset(granted)


def can(roles: Iterable[Role], *permissions: Permission) -> bool:
    """True when the roles grant at least one of `permissions`."""
    granted = permissions_for(roles)
    return any(permission in granted for permission in permissions)
