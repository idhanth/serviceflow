from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.enums import BookingStatus
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.customer import Customer
    from serviceflow.db.models.job import Job
    from serviceflow.db.models.service import Service
    from serviceflow.db.models.vehicle import Vehicle


class Booking(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A customer's request for service at a time.

    `requested_end` is always derived from the service duration on the server and
    never accepted from a client; the check constraint keeps that true even if a
    future code path forgets (PRD 8).
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("requested_end > requested_start", name="window_ordered"),
        Index("ix_bookings_organization_id_status", "organization_id", "status"),
        Index("ix_bookings_organization_id_requested_start", "organization_id", "requested_start"),
        Index("ix_bookings_organization_id_customer_id", "organization_id", "customer_id"),
        Index("ix_bookings_customer_id_requested_start", "customer_id", "requested_start"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT on vehicle and service: history must survive, which is why both are
    # archived/deactivated rather than deleted.
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status", native_enum=True),
        nullable=False,
        default=BookingStatus.PENDING,
    )
    customer_notes: Mapped[str | None] = mapped_column(Text)
    admin_notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(lazy="joined")
    vehicle: Mapped[Vehicle] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")
    job: Mapped[Job | None] = relationship(back_populates="booking", uselist=False)

    @property
    def is_open(self) -> bool:
        return self.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
