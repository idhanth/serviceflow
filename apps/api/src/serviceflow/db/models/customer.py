from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.user import User


class Customer(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A person's customer record within one organization.

    The same User may be a customer of several organizations; the unique
    constraint keeps them to one customer record per organization.

    `(organization_id, id)` is unique so that bookings can reference a customer
    *and its tenant* in one composite foreign key. That is what makes a booking
    whose customer belongs to another business impossible to store, rather than
    merely something the application checks.
    """

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        UniqueConstraint("organization_id", "id"),
        Index("ix_customers_organization_id_created_at", "organization_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Where the work happens. Field service goes to the customer, so this is the
    # address a technician drives to.
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Archived rather than deleted: past bookings and jobs still need to say who
    # they were for.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def archived(self) -> bool:
        return self.archived_at is not None
