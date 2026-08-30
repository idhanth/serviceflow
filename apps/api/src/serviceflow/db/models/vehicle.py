from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.customer import Customer


class Vehicle(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """The asset a job is performed on. Named for the auto-detailing demo (PRD 7)."""

    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year BETWEEN 1900 AND 2100", name="year_plausible"),
        Index("ix_vehicles_organization_id_customer_id", "organization_id", "customer_id"),
        Index("ix_vehicles_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_vehicles_customer_id_archived_at", "customer_id", "archived_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    make: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str | None] = mapped_column(String(40))
    license_plate: Mapped[str | None] = mapped_column(String(20), index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    # Soft delete: bookings and jobs reference vehicles, so removing the row would
    # destroy job history. Archived vehicles disappear from lists and cannot be
    # booked, but stay resolvable from the records that point at them.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="vehicles")

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    @property
    def display_name(self) -> str:
        return f"{self.year} {self.make} {self.model}"
