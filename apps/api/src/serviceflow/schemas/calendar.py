from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel

from serviceflow.db.models.enums import JobStatus
from serviceflow.db.models.job import Job


class CalendarEvent(BaseModel):
    """One scheduled job, with everything the grid needs to draw and label it."""

    id: uuid.UUID
    booking_id: uuid.UUID
    status: JobStatus
    scheduled_start: dt.datetime
    scheduled_end: dt.datetime
    duration_minutes: int
    employee_id: uuid.UUID
    employee_name: str
    service_id: uuid.UUID
    service_name: str
    customer_name: str
    vehicle_name: str

    @classmethod
    def from_model(cls, job: Job) -> CalendarEvent:
        booking = job.booking
        span = job.scheduled_end - job.scheduled_start
        return cls(
            id=job.id,
            booking_id=job.booking_id,
            status=job.status,
            scheduled_start=job.scheduled_start,
            scheduled_end=job.scheduled_end,
            duration_minutes=int(span.total_seconds() // 60),
            employee_id=job.employee_id,
            employee_name=job.employee.user.full_name,
            service_id=booking.service_id,
            service_name=booking.service.name,
            customer_name=booking.customer.user.full_name,
            vehicle_name=booking.vehicle.display_name,
        )


class CalendarFeed(BaseModel):
    timezone: str
    start: dt.date
    end: dt.date
    data: list[CalendarEvent]
    can_filter_by_employee: bool
