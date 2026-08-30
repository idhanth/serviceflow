from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from serviceflow.db.models.enums import JobStatus
from serviceflow.db.models.job import Job
from serviceflow.schemas.booking import BookingCustomer, BookingService, BookingVehicle


class JobEmployee(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    job_title: str


class JobRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    status: JobStatus
    scheduled_start: datetime
    scheduled_end: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    internal_notes: str | None = None
    employee: JobEmployee
    customer: BookingCustomer
    vehicle: BookingVehicle
    service: BookingService
    customer_notes: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, job: Job) -> JobRead:
        booking = job.booking
        return cls(
            id=job.id,
            booking_id=job.booking_id,
            status=job.status,
            scheduled_start=job.scheduled_start,
            scheduled_end=job.scheduled_end,
            started_at=job.started_at,
            completed_at=job.completed_at,
            internal_notes=job.internal_notes,
            employee=JobEmployee(
                id=job.employee.id,
                full_name=job.employee.user.full_name,
                job_title=job.employee.job_title,
            ),
            customer=BookingCustomer(
                id=booking.customer.id,
                full_name=booking.customer.user.full_name,
                email=booking.customer.user.email,
                phone=booking.customer.user.phone,
            ),
            vehicle=BookingVehicle.model_validate(booking.vehicle),
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
