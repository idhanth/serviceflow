from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from serviceflow.db.models.membership import OrganizationMembership


class User(UUIDPrimaryKey, Timestamps, Base):
    """A person. Identity lives with the auth provider; this is the local mirror.

    auth_provider_id is the subject claim from whichever provider is configured
    (the dev provider or Clerk), so swapping providers never rewrites foreign keys.
    """

    __tablename__ = "users"

    auth_provider_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    avatar_url: Mapped[str | None] = mapped_column(Text)

    # Only populated by the dev auth provider; Clerk owns credentials otherwise.
    password_hash: Mapped[str | None] = mapped_column(Text)

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
