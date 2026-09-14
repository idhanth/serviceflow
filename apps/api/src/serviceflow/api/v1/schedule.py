"""The schedule: technicians' hours and their jobs for a day or a week.

Dispatchers, managers, owners and analysts see the whole team; a technician sees
their own lane. Dates are local to the organization, so "this week" means the
business's week.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from serviceflow.api.deps import DbSession, ScheduleUser
from serviceflow.db.models.enums import JobStatus
from serviceflow.schemas.schedule import ScheduleFeed
from serviceflow.services.schedule_view import build_schedule

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("", response_model=ScheduleFeed, summary="Working hours and jobs in a date range")
def schedule(
    current_user: ScheduleUser,
    db: DbSession,
    start: Annotated[dt.date, Query(description="First local date, inclusive")],
    end: Annotated[dt.date | None, Query(description="Last local date, inclusive")] = None,
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
) -> ScheduleFeed:
    return build_schedule(
        db,
        current_user,
        start=start,
        end=end or start,
        employee_id=employee_id,
        status=status_filter,
    )
