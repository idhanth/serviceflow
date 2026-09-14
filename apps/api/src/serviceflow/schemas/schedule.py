"""The schedule: who is working, what is booked, and what still needs a technician."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel

from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job


class ScheduleEntry(BaseModel):
    """One job on the grid, with everything needed to draw and label it."""

    id: uuid.UUID
    booking_id: uuid.UUID
    booking_status: BookingStatus
    status: JobStatus
    scheduled_start: dt.datetime
    scheduled_end: dt.datetime
    duration_minutes: int
    employee_id: uuid.UUID | None
    employee_name: str | None
    service_id: uuid.UUID
    service_name: str
    customer_name: str
    customer_address: str | None

    @classmethod
    def from_model(cls, job: Job) -> ScheduleEntry:
        booking = job.booking
        span = job.scheduled_end - job.scheduled_start
        return cls(
            id=job.id,
            booking_id=job.booking_id,
            booking_status=booking.status,
            status=job.status,
            scheduled_start=job.scheduled_start,
            scheduled_end=job.scheduled_end,
            duration_minutes=int(span.total_seconds() // 60),
            employee_id=job.employee_id,
            employee_name=job.employee.user.full_name if job.employee else None,
            service_id=booking.service_id,
            service_name=booking.service.name,
            customer_name=booking.customer.user.full_name,
            customer_address=booking.customer.address,
        )


class WorkingWindow(BaseModel):
    """Local wall-clock hours, as "HH:MM" strings in the organization's timezone."""

    start: str
    end: str


class ScheduleDay(BaseModel):
    date: dt.date
    windows: list[WorkingWindow]
    unavailable_reason: str | None = None


class ScheduleLane(BaseModel):
    """One technician's row: their hours per day in the range."""

    employee_id: uuid.UUID
    full_name: str
    job_title: str
    days: list[ScheduleDay]


class ScheduleFeed(BaseModel):
    timezone: str
    start: dt.date
    end: dt.date
    lanes: list[ScheduleLane]
    entries: list[ScheduleEntry]
    can_view_team: bool
