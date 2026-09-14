"""What the API knows about the caller after a token is verified."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from serviceflow.auth.permissions import Permission, permissions_for
from serviceflow.db.models.enums import Role


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    """Provider-agnostic result of verifying a bearer token."""

    auth_provider_id: str
    email: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The resolved caller, scoped to exactly one organization per request."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    roles: frozenset[Role]
    is_platform_admin: bool = False
    permissions: frozenset[Permission] = field(default=frozenset())

    def __post_init__(self) -> None:
        if not self.permissions:
            object.__setattr__(
                self,
                "permissions",
                permissions_for(self.roles, platform_admin=self.is_platform_admin),
            )

    def has_role(self, *roles: Role) -> bool:
        return bool(self.roles.intersection(roles))

    def can(self, *permissions: Permission) -> bool:
        """True when the caller holds at least one of `permissions`."""
        return any(permission in self.permissions for permission in permissions)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """A verified caller before any tenant is chosen.

    Platform administration and the session lookup work at this level; every
    tenant-owned route needs a `CurrentUser` instead.
    """

    user_id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool
