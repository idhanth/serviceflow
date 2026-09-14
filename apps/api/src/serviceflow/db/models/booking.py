from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
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

# The statuses in which a booking still holds its slot.
OPEN_BOOKING_STATUSES = "('PENDING', 'CONFIRMED')"
NO_DUPLICATE_INDEX = "uq_bookings_no_duplicate_open"


class Booking(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A customer's appointment for a service at a time.

    Database guarantees, independent of application code:

    * `requested_end` is always derived from the service duration on the server;
      the check constraint keeps it after the start even if a code path forgets.
    * The customer and the service are referenced through composite foreign keys
      on `(organization_id, id)`, so a booking cannot pair Tenant A's customer
      with Tenant B's service - PostgreSQL refuses the row.
    * An open booking cannot be stored twice: the partial unique index rejects a
      second PENDING/CONFIRMED booking for the same customer, service and start.

    Technician overlap is enforced one level down, on `jobs`, by an exclusion
    constraint - the job is what holds a technician's time.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("requested_end > requested_start", name="window_ordered"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "customer_id"],
            ["customers.organization_id", "customers.id"],
            ondelete="RESTRICT",
        ),
        # RESTRICT: history must survive, which is why services are retired
        # rather than deleted.
        ForeignKeyConstraint(
            ["organization_id", "service_id"],
            ["services.organization_id", "services.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_bookings_organization_id_status", "organization_id", "status"),
        Index("ix_bookings_organization_id_requested_start", "organization_id", "requested_start"),
        Index("ix_bookings_organization_id_customer_id", "organization_id", "customer_id"),
        Index("ix_bookings_customer_id_requested_start", "customer_id", "requested_start"),
        Index(
            NO_DUPLICATE_INDEX,
            "organization_id",
            "customer_id",
            "service_id",
            "requested_start",
            unique=True,
            postgresql_where=text(f"status IN {OPEN_BOOKING_STATUSES}"),
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status", native_enum=True),
        nullable=False,
        default=BookingStatus.PENDING,
    )
    customer_notes: Mapped[str | None] = mapped_column(Text)
    admin_notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(
        lazy="joined",
        primaryjoin="Booking.customer_id == Customer.id",
        foreign_keys="Booking.customer_id",
    )
    service: Mapped[Service] = relationship(
        lazy="joined",
        primaryjoin="Booking.service_id == Service.id",
        foreign_keys="Booking.service_id",
    )
    job: Mapped[Job | None] = relationship(
        back_populates="booking",
        uselist=False,
        primaryjoin="Booking.id == Job.booking_id",
        foreign_keys="Job.booking_id",
    )

    @property
    def is_open(self) -> bool:
        return self.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
