from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, JobStatus


class BookingVehicle(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    license_plate: str | None = None
    color: str | None = None


class BookingService(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    duration_minutes: int
    base_price: str


class BookingCustomer(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    phone: str | None = None


class BookingJobSummary(BaseModel):
    """The job a confirmed booking produced, as the booking's reader sees it."""

    id: uuid.UUID
    status: JobStatus
    scheduled_start: datetime
    scheduled_end: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    employee_name: str


class BookingRead(BaseModel):
    id: uuid.UUID
    status: BookingStatus
    requested_start: datetime
    requested_end: datetime
    customer_notes: str | None = None
    admin_notes: str | None = None
    vehicle: BookingVehicle
    service: BookingService
    customer: BookingCustomer | None = None
    job: BookingJobSummary | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, booking: Booking, *, include_internal: bool = False) -> BookingRead:
        """`include_internal` gates admin-only fields: notes and customer contact."""
        job = booking.job
        return cls(
            id=booking.id,
            status=booking.status,
            requested_start=booking.requested_start,
            requested_end=booking.requested_end,
            customer_notes=booking.customer_notes,
            admin_notes=booking.admin_notes if include_internal else None,
            vehicle=BookingVehicle.model_validate(booking.vehicle),
            service=BookingService(
                id=booking.service.id,
                name=booking.service.name,
                duration_minutes=booking.service.duration_minutes,
                base_price=str(booking.service.base_price),
            ),
            customer=(
                BookingCustomer(
                    id=booking.customer.id,
                    full_name=booking.customer.user.full_name,
                    email=booking.customer.user.email,
                    phone=booking.customer.user.phone,
                )
                if include_internal
                else None
            ),
            job=(
                BookingJobSummary(
                    id=job.id,
                    status=job.status,
                    scheduled_start=job.scheduled_start,
                    scheduled_end=job.scheduled_end,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    employee_name=job.employee.user.full_name,
                )
                if job is not None
                else None
            ),
            created_at=booking.created_at,
        )


class BookingCreate(BaseModel):
    """Note the absence of an end time: it is derived from the service (PRD 8)."""

    customer_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID
    service_id: uuid.UUID
    requested_start: AwareDatetime
    customer_notes: str | None = Field(default=None, max_length=2000)


class BookingConfirm(BaseModel):
    employee_id: uuid.UUID
    admin_notes: str | None = Field(default=None, max_length=2000)


class BookingReject(BaseModel):
    admin_notes: str | None = Field(default=None, max_length=2000)


class BookingCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class BookingReschedule(BaseModel):
    requested_start: AwareDatetime


class BookingNotesUpdate(BaseModel):
    admin_notes: str | None = Field(default=None, max_length=2000)


class AssignableEmployee(BaseModel):
    """A candidate for assignment. Phase 4 adds availability and workload here."""

    id: uuid.UUID
    full_name: str
    job_title: str
    active: bool
