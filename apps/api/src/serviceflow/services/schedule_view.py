"""Building the schedule: technicians' working hours alongside their jobs.

Hours and jobs are loaded in a fixed number of queries for the whole range -
one for the lanes, one for weekly windows, one for overrides, one for jobs -
however many technicians or days are on screen.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.auth.permissions import Permission as P
from serviceflow.auth.principal import CurrentUser
from serviceflow.core.errors import InvalidRole, ValidationFailed
from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import JobStatus
from serviceflow.db.models.user import User
from serviceflow.schemas.schedule import (
    ScheduleDay,
    ScheduleEntry,
    ScheduleFeed,
    ScheduleLane,
    WorkingWindow,
)
from serviceflow.services import jobs as jobs_service
from serviceflow.services.availability import (
    DateOverride,
    WeeklyWindow,
    merge,
    windows_for_date,
)
from serviceflow.services.employees import get_employee_for_user
from serviceflow.services.scheduling import organization_timezone

MAX_RANGE_DAYS = 31


def _clock(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}"


def working_days(
    db: Session,
    organization_id: uuid.UUID,
    employee_ids: list[uuid.UUID],
    dates: list[dt.date],
) -> dict[uuid.UUID, list[ScheduleDay]]:
    """Each employee's resolved working windows for each date, in two queries."""
    if not employee_ids or not dates:
        return {}

    weekly: dict[uuid.UUID, list[WeeklyWindow]] = defaultdict(list)
    for row in db.scalars(
        select(EmployeeAvailability).where(
            EmployeeAvailability.organization_id == organization_id,
            EmployeeAvailability.employee_id.in_(employee_ids),
        )
    ):
        weekly[row.employee_id].append(
            WeeklyWindow(
                day_of_week=row.day_of_week, start_time=row.start_time, end_time=row.end_time
            )
        )

    overrides: dict[tuple[uuid.UUID, dt.date], DateOverride] = {}
    for override_row in db.scalars(
        select(AvailabilityOverride).where(
            AvailabilityOverride.organization_id == organization_id,
            AvailabilityOverride.employee_id.in_(employee_ids),
            AvailabilityOverride.date >= dates[0],
            AvailabilityOverride.date <= dates[-1],
        )
    ):
        overrides[(override_row.employee_id, override_row.date)] = DateOverride(
            date=override_row.date,
            available=override_row.available,
            start_time=override_row.start_time,
            end_time=override_row.end_time,
            reason=override_row.reason,
        )

    result: dict[uuid.UUID, list[ScheduleDay]] = {}
    for employee_id in employee_ids:
        days: list[ScheduleDay] = []
        for date in dates:
            override = overrides.get((employee_id, date))
            windows = merge(windows_for_date(date, weekly[employee_id], override))
            reason = None
            if not windows:
                reason = (
                    (override.reason or "Time off")
                    if override is not None and not override.available
                    else "Not scheduled"
                )
            days.append(
                ScheduleDay(
                    date=date,
                    windows=[
                        WorkingWindow(start=_clock(w.start), end=_clock(w.end)) for w in windows
                    ],
                    unavailable_reason=reason,
                )
            )
        result[employee_id] = days
    return result


def build_schedule(
    db: Session,
    current_user: CurrentUser,
    *,
    start: dt.date,
    end: dt.date,
    employee_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
) -> ScheduleFeed:
    if end < start:
        raise ValidationFailed(
            "The end date can't be before the start date.",
            details={"fields": {"end": "Must be on or after the start date."}},
        )
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ValidationFailed(
            "That range is too wide. Ask for a month or less at a time.",
            details={"fields": {"end": f"At most {MAX_RANGE_DAYS} days."}},
        )

    organization_id = current_user.organization_id
    timezone = organization_timezone(db, organization_id)
    tz = ZoneInfo(timezone)
    range_start = dt.datetime.combine(start, dt.time.min, tzinfo=tz)
    range_end = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=tz)

    team = current_user.can(P.SCHEDULE_READ)
    if team:
        statement = (
            select(Employee)
            .join(User, User.id == Employee.user_id)
            .where(Employee.organization_id == organization_id, Employee.active.is_(True))
            .order_by(User.first_name, User.last_name, Employee.id)
        )
        if employee_id is not None:
            statement = statement.where(Employee.id == employee_id)
        employees = list(db.scalars(statement).unique())
    elif current_user.can(P.SCHEDULE_OWN):
        employees = [get_employee_for_user(db, organization_id, current_user.user_id)]
    else:
        raise InvalidRole()

    dates = [start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)]
    hours = working_days(db, organization_id, [e.id for e in employees], dates)

    jobs = jobs_service.jobs_in_range(
        db,
        organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        start=range_start,
        end=range_end,
        employee_id=employee_id,
        status=status,
    )
    if not team:
        jobs = [job for job in jobs if job.employee_id == employees[0].id]

    return ScheduleFeed(
        timezone=timezone,
        start=start,
        end=end,
        lanes=[
            ScheduleLane(
                employee_id=employee.id,
                full_name=employee.user.full_name,
                job_title=employee.job_title,
                days=hours.get(employee.id, []),
            )
            for employee in employees
        ],
        entries=[ScheduleEntry.from_model(job) for job in jobs],
        can_view_team=team,
    )
