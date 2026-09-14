from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.schemas.booking import BookingCustomer, BookingService


class JobEmployee(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    job_title: str


class JobRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    booking_status: BookingStatus
    status: JobStatus
    scheduled_start: datetime
    scheduled_end: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    internal_notes: str | None = None
    employee: JobEmployee | None = None
    customer: BookingCustomer
    service: BookingService
    customer_notes: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> JobRead:
        booking = job.booking
        return cls(
            id=job.id,
            booking_id=job.booking_id,
            booking_status=booking.status,
            status=job.status,
            scheduled_start=job.scheduled_start,
            scheduled_end=job.scheduled_end,
            started_at=job.started_at,
            completed_at=job.completed_at,
            internal_notes=job.internal_notes,
            employee=(
                JobEmployee(
                    id=job.employee.id,
                    full_name=job.employee.user.full_name,
                    job_title=job.employee.job_title,
                )
                if job.employee is not None
                else None
            ),
            customer=BookingCustomer(
                id=booking.customer.id,
                full_name=booking.customer.user.full_name,
                email=booking.customer.user.email,
                phone=booking.customer.user.phone,
                address=booking.customer.address,
            ),
            service=BookingService(
                id=booking.service.id,
                name=booking.service.name,
                duration_minutes=booking.service.duration_minutes,
                base_price=str(booking.service.base_price),
            ),
            customer_notes=booking.customer_notes,
            created_at=job.created_at,
        )


class JobComplete(BaseModel):
    internal_notes: str | None = Field(default=None, max_length=2000)


class JobReassign(BaseModel):
    employee_id: uuid.UUID


class JobUpdate(BaseModel):
    """PATCH /jobs/{id}: move the status along, assign a technician, or edit notes.

    Status may only move forward along the state machine; the service layer
    refuses anything else with INVALID_STATE_TRANSITION.
    """

    status: JobStatus | None = None
    employee_id: uuid.UUID | None = None
    scheduled_start: AwareDatetime | None = None
    internal_notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _one_change(self) -> Self:
        changes = [
            name
            for name in ("status", "employee_id", "scheduled_start")
            if getattr(self, name) is not None
        ]
        if self.status is JobStatus.SCHEDULED and self.employee_id is not None:
            changes = ["employee_id"]
        if len(changes) > 1:
            raise ValueError("Change the status, the technician or the time - one at a time.")
        if self.status is JobStatus.NEW:
            raise ValueError("A job can't be moved back to new.")
        if self.status is JobStatus.SCHEDULED and self.employee_id is None:
            raise ValueError("Scheduling a job needs a technician (employee_id).")
        return self
