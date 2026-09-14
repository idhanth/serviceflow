from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, JobStatus


class BookingService(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    base_price: str


class BookingCustomer(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    phone: str | None = None
    address: str | None = None


class BookingJobSummary(BaseModel):
    """The job behind a booking, as the booking's reader sees it."""

    id: uuid.UUID
    status: JobStatus
    scheduled_start: datetime
    scheduled_end: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    employee_id: uuid.UUID | None = None
    employee_name: str | None = None


class BookingRead(BaseModel):
    id: uuid.UUID
    status: BookingStatus
    requested_start: datetime
    requested_end: datetime
    customer_notes: str | None = None
    admin_notes: str | None = None
    service: BookingService
    customer: BookingCustomer | None = None
    job: BookingJobSummary | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, booking: Booking, *, include_internal: bool = False) -> BookingRead:
        """`include_internal` gates staff-only fields: internal notes and contact details."""
        job = booking.job
        customer = booking.customer
        return cls(
            id=booking.id,
            status=booking.status,
            requested_start=booking.requested_start,
            requested_end=booking.requested_end,
            customer_notes=booking.customer_notes,
            admin_notes=booking.admin_notes if include_internal else None,
            service=BookingService(
                id=booking.service.id,
                name=booking.service.name,
                duration_minutes=booking.service.duration_minutes,
                base_price=str(booking.service.base_price),
            ),
            customer=(
                BookingCustomer(
                    id=customer.id,
                    full_name=customer.user.full_name,
                    email=customer.user.email,
                    phone=customer.user.phone,
                    address=customer.address,
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
                    employee_id=job.employee_id,
                    employee_name=job.employee.user.full_name if job.employee else None,
                )
                if job is not None
                else None
            ),
            created_at=booking.created_at,
        )


class BookingCreate(BaseModel):
    """Note the absence of an end time: it is derived from the service duration.

    `customer_id` is required from staff and ignored-or-refused from a customer,
    who can only book for themselves. `employee_id` is optional: without it the
    booking waits for a dispatcher to assign someone.
    """

    customer_id: uuid.UUID | None = None
    service_id: uuid.UUID
    employee_id: uuid.UUID | None = None
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


class BookingUpdate(BaseModel):
    """PATCH /bookings/{id}: one change at a time, plus optional notes.

    Each change is a different transaction with different rules (a move re-runs
    the scheduling checks; a cancellation closes the job), so combining them in
    one request would make a partial failure ambiguous.
    """

    status: BookingStatus | None = None
    employee_id: uuid.UUID | None = None
    requested_start: AwareDatetime | None = None
    admin_notes: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _one_change(self) -> Self:
        changes = [
            name
            for name in ("status", "employee_id", "requested_start")
            if getattr(self, name) is not None
        ]
        if self.status is BookingStatus.CONFIRMED and self.employee_id is not None:
            changes = ["employee_id"]
        if len(changes) > 1:
            raise ValueError("Change the status, the technician or the time - one at a time.")
        if self.status is BookingStatus.CONFIRMED and self.employee_id is None:
            raise ValueError("Confirming a booking needs a technician (employee_id).")
        if self.status is BookingStatus.PENDING:
            raise ValueError("A booking can't be moved back to pending.")
        return self


class BookingNotesUpdate(BaseModel):
    admin_notes: str | None = Field(default=None, max_length=2000)


class AssignableEmployee(BaseModel):
    """A ranked candidate, with the facts behind their position."""

    id: uuid.UUID
    full_name: str
    job_title: str
    available: bool
    conflict: bool
    assignable: bool
    reason: str | None = None
    jobs_today: int
    scheduled_minutes_today: int
    conflicting_job_id: uuid.UUID | None = None
