"""Ranking employees for an assignment (PRD 11).

Deterministic business logic, not a model: the same inputs always produce the
same order, and every position is explainable from the fields returned alongside
it. The admin UI renders those fields directly, so the reason a technician is
ranked where they are is visible rather than implied.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from serviceflow.db.models.employee import Employee
from serviceflow.db.models.job import Job
from serviceflow.db.models.service import Service
from serviceflow.services.availability import evaluate_window
from serviceflow.services.conflicts import TIME_HOLDING_STATUSES, overlapping_jobs
from serviceflow.services.scheduling import date_overrides, organization_timezone, weekly_windows


@dataclass(frozen=True, slots=True)
class EmployeeRecommendation:
    """One candidate, with everything needed to explain their position."""

    employee_id: uuid.UUID
    full_name: str
    job_title: str
    available: bool
    conflict: bool
    reason: str | None
    jobs_today: int
    scheduled_minutes_today: int
    conflicting_job_id: uuid.UUID | None = None

    @property
    def assignable(self) -> bool:
        return self.available and not self.conflict

    @property
    def sort_key(self) -> tuple[int, int, int, str, str]:
        """Assignable first, then the lightest day, then a stable alphabetical tiebreak.

        Every component is total and deterministic - two candidates can never
        compare equal, because the id is the final term.
        """
        return (
            0 if self.assignable else 1,
            self.jobs_today,
            self.scheduled_minutes_today,
            self.full_name,
            str(self.employee_id),
        )


def local_day_bounds(moment: dt.datetime, timezone: str) -> tuple[dt.datetime, dt.datetime]:
    """The UTC instants bracketing the local calendar day `moment` falls in."""
    tz = ZoneInfo(timezone)
    local_date = moment.astimezone(tz).date()
    start = dt.datetime.combine(local_date, dt.time.min, tzinfo=tz)
    end = dt.datetime.combine(local_date + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
    return start, end


def _workload(
    db: Session,
    *,
    organization_id: uuid.UUID,
    day_start: dt.datetime,
    day_end: dt.datetime,
    exclude_job_id: uuid.UUID | None,
) -> dict[uuid.UUID, tuple[int, int]]:
    """Per-employee (job count, scheduled minutes) for one local day, in one query.

    Cancelled work does not count towards a workload, and a job being moved is
    excluded so it is not counted against its own reassignment.
    """
    minutes = func.sum(func.extract("epoch", Job.scheduled_end - Job.scheduled_start) / 60)
    statement = (
        select(Job.employee_id, func.count(), minutes)
        .where(
            Job.organization_id == organization_id,
            Job.employee_id.is_not(None),
            Job.status.in_(TIME_HOLDING_STATUSES),
            Job.scheduled_start >= day_start,
            Job.scheduled_start < day_end,
        )
        .group_by(Job.employee_id)
    )
    if exclude_job_id is not None:
        statement = statement.where(Job.id != exclude_job_id)

    return {row[0]: (int(row[1]), int(row[2] or 0)) for row in db.execute(statement).all()}


def recommend_employees(
    db: Session,
    organization_id: uuid.UUID,
    *,
    service: Service,
    start: dt.datetime,
    end: dt.datetime,
    exclude_job_id: uuid.UUID | None = None,
) -> list[EmployeeRecommendation]:
    """Rank the active employees qualified for `service` for the window [start, end).

    Unqualified and deactivated employees are left out entirely - they could never
    be assigned. Everyone qualified is returned, including those who are busy or
    off that day, so the admin can see *why* rather than wondering who is missing.
    """
    candidates = list(
        db.scalars(
            select(Employee)
            .where(
                Employee.organization_id == organization_id,
                Employee.active.is_(True),
                Employee.services.any(Service.id == service.id),
            )
            .options(selectinload(Employee.services))
        ).unique()
    )
    if not candidates:
        return []

    timezone = organization_timezone(db, organization_id)
    day_start, day_end = local_day_bounds(start, timezone)
    workload = _workload(
        db,
        organization_id=organization_id,
        day_start=day_start,
        day_end=day_end,
        exclude_job_id=exclude_job_id,
    )

    recommendations: list[EmployeeRecommendation] = []
    for employee in candidates:
        verdict = evaluate_window(
            start,
            end,
            timezone=timezone,
            weekly=weekly_windows(db, employee.id),
            overrides=date_overrides(db, employee.id),
        )
        clashes = overlapping_jobs(
            db,
            organization_id=organization_id,
            employee_id=employee.id,
            start=start,
            end=end,
            exclude_job_id=exclude_job_id,
        )
        jobs_today, minutes_today = workload.get(employee.id, (0, 0))

        reason = verdict.reason
        if clashes and reason is None:
            other = clashes[0]
            local_start = other.scheduled_start.astimezone(ZoneInfo(timezone))
            local_end = other.scheduled_end.astimezone(ZoneInfo(timezone))
            reason = f"Already booked {local_start:%-I:%M%p}-{local_end:%-I:%M%p}".replace(
                "AM", "am"
            ).replace("PM", "pm")

        recommendations.append(
            EmployeeRecommendation(
                employee_id=employee.id,
                full_name=employee.user.full_name,
                job_title=employee.job_title,
                available=verdict.available,
                conflict=bool(clashes),
                reason=reason,
                jobs_today=jobs_today,
                scheduled_minutes_today=minutes_today,
                conflicting_job_id=clashes[0].id if clashes else None,
            )
        )

    return sorted(recommendations, key=lambda item: item.sort_key)
