"""What the API knows about the caller after a token is verified."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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

    def has_role(self, *roles: Role) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in self.roles
