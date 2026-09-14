"""The scheduling policy consulted whenever work is assigned to an employee.

Phase 3 established this seam: `check_assignment` is called from inside the
booking-confirmation transaction with the live `Session`, and reschedule and
reassign call it too. Phase 4 fills it in without changing any of those callers.

`SchedulingPolicy` is still the extension point. `QualificationPolicy` remains as
the base layer (organization, active, qualified) and `AvailabilityPolicy` - the
default from phase 4 onward - adds the working-hours check, the advisory lock and
overlap detection on top of it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.core.errors import InvalidSchedule, ScheduleConflict, ValidationFailed
from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.services.availability import (
    DateOverride,
    WeeklyWindow,
    evaluate_window,
)
from serviceflow.services.conflicts import lock_employee_schedule, overlapping_jobs


@dataclass(frozen=True, slots=True)
class AssignmentRequest:
    """Everything a scheduling decision needs."""

    organization_id: uuid.UUID
    employee: Employee
    service: Service
    start: datetime
    end: datetime
    # Set when rescheduling or reassigning, so a job is not treated as its own conflict.
    exclude_job_id: uuid.UUID | None = None


class SchedulingPolicy(Protocol):
    def check_assignment(self, db: Session, request: AssignmentRequest) -> None:
        """Raise an AppError if this employee must not take this work."""
        ...


# --------------------------------------------------------------- loading


def organization_timezone(db: Session, organization_id: uuid.UUID) -> str:
    organization = db.get(Organization, organization_id)
    return organization.timezone if organization is not None else "UTC"


def weekly_windows(db: Session, employee_id: uuid.UUID) -> list[WeeklyWindow]:
    rows = db.scalars(
        select(EmployeeAvailability).where(EmployeeAvailability.employee_id == employee_id)
    )
    return [
        WeeklyWindow(day_of_week=row.day_of_week, start_time=row.start_time, end_time=row.end_time)
        for row in rows
    ]


def date_overrides(db: Session, employee_id: uuid.UUID) -> dict[dt.date, DateOverride]:
    rows = db.scalars(
        select(AvailabilityOverride).where(AvailabilityOverride.employee_id == employee_id)
    )
    return {
        row.date: DateOverride(
            date=row.date,
            available=row.available,
            start_time=row.start_time,
            end_time=row.end_time,
            reason=row.reason,
        )
        for row in rows
    }


def conflict_message(name: str, start: datetime, end: datetime, timezone: str) -> str:
    """ "Alex Morgan is already booked from 2:00 PM-3:00 PM. Choose ..." in the shop's time."""
    tz = ZoneInfo(timezone)
    local_start, local_end = start.astimezone(tz), end.astimezone(tz)
    return (
        f"{name} is already booked from {_clock(local_start)}–{_clock(local_end)}."  # noqa: RUF001
        " Choose another employee or time."
    )


def _clock(moment: datetime) -> str:
    return moment.strftime("%-I:%M %p")


# --------------------------------------------------------------- policies


class QualificationPolicy:
    """Who is even eligible: in the organization, active, and trained for the work."""

    def check_assignment(self, db: Session, request: AssignmentRequest) -> None:
        employee = request.employee
        service = request.service

        if employee.organization_id != request.organization_id:
            raise ValidationFailed(
                "That employee isn't part of this organization.",
                details={"fields": {"employee_id": "Unknown employee."}},
            )

        if not employee.active:
            raise ValidationFailed(
                f"{employee.user.full_name} is deactivated and can't be assigned work.",
                details={"fields": {"employee_id": "Employee is not active."}},
            )

        qualified = {qualification.id for qualification in employee.services}
        if service.id not in qualified:
            raise ValidationFailed(
                f"{employee.user.full_name} isn't qualified for {service.name}.",
                details={"fields": {"employee_id": "Not qualified for this service."}},
            )


class AvailabilityPolicy(QualificationPolicy):
    """The full phase 4 rules.

    Order matters. Eligibility is checked first because it is cheap and its
    failures are the admin's fault rather than a race. Only then does the
    transaction take the advisory lock and look for overlaps, so a request that
    was never going to succeed does not serialise everyone else.
    """

    def check_assignment(self, db: Session, request: AssignmentRequest) -> None:
        super().check_assignment(db, request)

        employee = request.employee

        verdict = evaluate_window(
            request.start,
            request.end,
            timezone=organization_timezone(db, request.organization_id),
            weekly=weekly_windows(db, employee.id),
            overrides=date_overrides(db, employee.id),
        )
        if verdict.blocked:
            raise InvalidSchedule(
                f"{employee.user.full_name} isn't available then. {verdict.reason}",
                details={"fields": {"employee_id": verdict.reason}},
            )

        # From here on the answer depends on rows another transaction could be
        # writing right now, so serialise this employee's schedule first.
        lock_employee_schedule(db, employee.id)

        clashes = overlapping_jobs(
            db,
            organization_id=request.organization_id,
            employee_id=employee.id,
            start=request.start,
            end=request.end,
            exclude_job_id=request.exclude_job_id,
        )
        if clashes:
            first = clashes[0]
            raise ScheduleConflict(
                conflict_message(
                    employee.user.full_name,
                    first.scheduled_start,
                    first.scheduled_end,
                    organization_timezone(db, request.organization_id),
                ),
                details={
                    "fields": {"employee_id": "Already assigned during this window."},
                    "conflicting_job_id": str(first.id),
                },
            )


_policy: SchedulingPolicy = AvailabilityPolicy()


def get_scheduling_policy() -> SchedulingPolicy:
    return _policy


def set_scheduling_policy(policy: SchedulingPolicy) -> None:
    """Swap the policy. Used by tests to isolate a single rule."""
    global _policy
    _policy = policy


def reset_scheduling_policy() -> None:
    set_scheduling_policy(AvailabilityPolicy())
