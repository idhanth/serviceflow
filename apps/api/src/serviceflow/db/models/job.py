from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.enums import JobStatus
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.booking import Booking
    from serviceflow.db.models.employee import Employee
    from serviceflow.db.models.job_note import JobNote
    from serviceflow.db.models.job_photo import JobPhoto


class Job(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """The work created when a booking is confirmed.

    `booking_id` is unique: confirming a booking twice cannot produce two jobs,
    and that guarantee is held by the database rather than by application logic
    alone (PRD 8, 14).
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("booking_id", name="one_job_per_booking"),
        CheckConstraint("scheduled_end > scheduled_start", name="window_ordered"),
        Index("ix_jobs_organization_id_status", "organization_id", "status"),
        Index("ix_jobs_employee_id_scheduled_start", "employee_id", "scheduled_start"),
        Index("ix_jobs_organization_id_scheduled_start", "organization_id", "scheduled_start"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status", native_enum=True),
        nullable=False,
        default=JobStatus.ASSIGNED,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    internal_notes: Mapped[str | None] = mapped_column(Text)

    booking: Mapped[Booking] = relationship(back_populates="job", lazy="joined")
    employee: Mapped[Employee] = relationship(lazy="joined")
    notes: Mapped[list[JobNote]] = relationship(back_populates="job", cascade="all, delete-orphan")
    photos: Mapped[list[JobPhoto]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.CANCELLED)
