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
)
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
    """The field work behind a booking.

    Every booking has exactly one job from the moment it is created. A job is
    NEW while nobody is assigned, SCHEDULED once a technician holds the time,
    then IN_PROGRESS and COMPLETED - or CANCELLED with its booking.

    Database guarantees:

    * `booking_id` is unique: a booking can never produce two jobs.
    * The booking and the technician are referenced through composite foreign
      keys on `(organization_id, id)`, so a job cannot assign another tenant's
      employee.
    * NEW means unassigned and SCHEDULED/IN_PROGRESS/COMPLETED mean assigned;
      two check constraints hold that pairing.
    * `jobs_no_overlapping_assignments` (an exclusion constraint created in the
      migration, since SQLAlchemy metadata cannot express it) forbids two live
      jobs for one technician whose time ranges overlap.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("booking_id", name="one_job_per_booking"),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("scheduled_end > scheduled_start", name="window_ordered"),
        CheckConstraint("status <> 'NEW' OR employee_id IS NULL", name="new_jobs_unassigned"),
        CheckConstraint(
            "status IN ('NEW', 'CANCELLED') OR employee_id IS NOT NULL",
            name="active_jobs_assigned",
        ),
        ForeignKeyConstraint(
            ["organization_id", "booking_id"],
            ["bookings.organization_id", "bookings.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_jobs_organization_id_status", "organization_id", "status"),
        Index("ix_jobs_employee_id_scheduled_start", "employee_id", "scheduled_start"),
        Index("ix_jobs_organization_id_scheduled_start", "organization_id", "scheduled_start"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Null while the job is NEW; see the check constraints above.
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)

    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status", native_enum=True),
        nullable=False,
        default=JobStatus.NEW,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    internal_notes: Mapped[str | None] = mapped_column(Text)

    booking: Mapped[Booking] = relationship(
        back_populates="job",
        lazy="joined",
        primaryjoin="Job.booking_id == Booking.id",
        foreign_keys="Job.booking_id",
    )
    employee: Mapped[Employee | None] = relationship(
        lazy="joined",
        primaryjoin="Job.employee_id == Employee.id",
        foreign_keys="Job.employee_id",
    )
    notes: Mapped[list[JobNote]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        primaryjoin="Job.id == JobNote.job_id",
        foreign_keys="JobNote.job_id",
    )
    photos: Mapped[list[JobPhoto]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        primaryjoin="Job.id == JobPhoto.job_id",
        foreign_keys="JobPhoto.job_id",
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.CANCELLED)

    @property
    def holds_time(self) -> bool:
        """Whether this job occupies its technician's calendar."""
        return self.employee_id is not None and self.status in (
            JobStatus.SCHEDULED,
            JobStatus.IN_PROGRESS,
            JobStatus.COMPLETED,
        )
