from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.user import User
    from serviceflow.db.models.vehicle import Vehicle


class Customer(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A person's customer record within one organization.

    The same User may be a customer of several organizations; the unique
    constraint keeps them to one customer record per organization.
    """

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        Index("ix_customers_organization_id_created_at", "organization_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(lazy="joined")
    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
