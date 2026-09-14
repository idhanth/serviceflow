"""Members of a tenant, platform tenants and the operations dashboard."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, EmailStr, Field

from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.schemas.schedule import ScheduleEntry


class MemberRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    status: MembershipStatus
    can_sign_in: bool
    created_at: dt.datetime


class MemberInvite(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    role: Role
    job_title: str | None = Field(default=None, max_length=120)


class MemberUpdate(BaseModel):
    role: Role | None = None
    status: MembershipStatus | None = None


class TenantSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    created_at: dt.datetime
    members: int
    customers: int
    employees: int
    bookings: int
    jobs: int


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    email: EmailStr
    timezone: str = Field(default="America/Chicago", max_length=64)
    owner_email: EmailStr
    owner_first_name: str = Field(min_length=1, max_length=100)
    owner_last_name: str = Field(min_length=1, max_length=100)


class CustomerBrief(BaseModel):
    id: uuid.UUID
    full_name: str
    address: str | None
    created_at: dt.datetime


class DashboardCounts(BaseModel):
    bookings_today: int
    jobs_in_progress: int
    jobs_completed_today: int
    jobs_remaining_today: int
    technicians_working_today: int
    technicians_total: int
    unassigned_jobs: int
    pending_bookings: int


class DashboardRead(BaseModel):
    """Everything on the operations dashboard, each with a job to do.

    `needs_attention` is work that is at risk: jobs nobody is assigned to that
    start soon, and scheduled jobs whose start time has passed without anyone
    starting them.
    """

    timezone: str
    date: dt.date
    counts: DashboardCounts
    needs_attention: list[ScheduleEntry]
    overdue: list[ScheduleEntry]
    upcoming: list[ScheduleEntry]
    recent_customers: list[CustomerBrief]
