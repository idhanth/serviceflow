"""Calendar feed for the schedule views (PRD 33).

Returns the jobs in a date range, scoped by role: an admin sees the whole shop,
an employee sees only their own work. The range is interpreted in the
organization's timezone, so "this week" means the shop's week.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from serviceflow.api.deps import DbSession, EmployeeUser
from serviceflow.core.errors import ValidationFailed
from serviceflow.db.models.enums import JobStatus, Role
from serviceflow.schemas.calendar import CalendarEvent, CalendarFeed
from serviceflow.services import jobs as jobs_service
from serviceflow.services.scheduling import organization_timezone

router = APIRouter(prefix="/calendar", tags=["calendar"])

MAX_RANGE_DAYS = 62


@router.get("", response_model=CalendarFeed, summary="Scheduled work in a date range")
def calendar(
    current_user: EmployeeUser,
    db: DbSession,
    start: Annotated[dt.date, Query(description="First local date, inclusive")],
    end: Annotated[dt.date, Query(description="Last local date, inclusive")],
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
) -> CalendarFeed:
    if end < start:
        raise ValidationFailed(
            "The end date can't be before the start date.",
            details={"fields": {"end": "Must be on or after the start date."}},
        )
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValidationFailed(
            "That range is too wide. Ask for two months or less at a time.",
            details={"fields": {"end": f"At most {MAX_RANGE_DAYS} days."}},
        )

    timezone = organization_timezone(db, current_user.organization_id)
    tz = ZoneInfo(timezone)
    # Local dates, converted to the absolute instants that bracket them.
    range_start = dt.datetime.combine(start, dt.time.min, tzinfo=tz)
    range_end = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=tz)

    events = jobs_service.jobs_in_range(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        start=range_start,
        end=range_end,
        employee_id=employee_id,
        service_id=service_id,
        status=status_filter,
    )

    return CalendarFeed(
        timezone=timezone,
        start=start,
        end=end,
        # Customer names are internal detail; only staff reach this endpoint.
        data=[CalendarEvent.from_model(job) for job in events],
        can_filter_by_employee=current_user.has_role(Role.ADMIN),
    )
