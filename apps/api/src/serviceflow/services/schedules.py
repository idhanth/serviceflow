"""Managing an employee's weekly schedule and date overrides.

Access follows PRD 6: an admin manages anyone in their organization, an employee
manages their own availability and nobody else's. That decision is made here, not
in the routes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from serviceflow.core.errors import Forbidden, NotFound, ValidationFailed
from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, Role
from serviceflow.services import audit
from serviceflow.services.employees import get_employee, get_employee_for_user

MAX_WEEKLY_WINDOWS = 21  # three windows a day is already an unusual shift pattern


def resolve_manageable_employee(
    db: Session,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Employee:
    """The employee whose schedule this caller may read and change."""
    if Role.ADMIN in roles:
        return get_employee(db, organization_id, employee_id)

    own = get_employee_for_user(db, organization_id, user_id)
    if own.id != employee_id:
        raise Forbidden("You can only manage your own availability.")
    return own


def get_weekly(db: Session, employee: Employee) -> list[EmployeeAvailability]:
    return list(
        db.scalars(
            select(EmployeeAvailability)
            .where(EmployeeAvailability.employee_id == employee.id)
            .order_by(EmployeeAvailability.day_of_week, EmployeeAvailability.start_time)
        )
    )


def get_overrides(
    db: Session, employee: Employee, *, since: dt.date | None = None
) -> list[AvailabilityOverride]:
    statement = select(AvailabilityOverride).where(AvailabilityOverride.employee_id == employee.id)
    if since is not None:
        statement = statement.where(AvailabilityOverride.date >= since)
    return list(db.scalars(statement.order_by(AvailabilityOverride.date)))


def _validate_windows(windows: list[tuple[int, dt.time, dt.time]]) -> None:
    if len(windows) > MAX_WEEKLY_WINDOWS:
        raise ValidationFailed(
            "That's more shifts than we can store for one week.",
            details={"fields": {"windows": f"At most {MAX_WEEKLY_WINDOWS}."}},
        )

    by_day: dict[int, list[tuple[dt.time, dt.time]]] = {}
    for day, start, end in windows:
        if not 0 <= day <= 6:
            raise ValidationFailed(
                "That isn't a valid day of the week.",
                details={"fields": {"day_of_week": "Use 0 (Monday) to 6 (Sunday)."}},
            )
        if end <= start:
            raise ValidationFailed(
                "Each shift has to end after it starts.",
                details={"fields": {"end_time": "Must be later than the start time."}},
            )
        by_day.setdefault(day, []).append((start, end))

    # Overlapping windows on one day would double-count the same hours.
    for entries in by_day.values():
        ordered = sorted(entries)
        for (_, previous_end), (next_start, _) in pairwise(ordered):
            if next_start < previous_end:
                raise ValidationFailed(
                    "Two shifts on the same day overlap.",
                    details={"fields": {"windows": "Shifts on a day cannot overlap."}},
                )


def replace_weekly(
    db: Session,
    employee: Employee,
    windows: list[tuple[int, dt.time, dt.time]],
    actor_user_id: uuid.UUID | None = None,
) -> list[EmployeeAvailability]:
    """Replace the whole weekly schedule in one transaction.

    Wholesale replacement rather than per-row edits: the UI presents a week at a
    time, and a partial failure would leave a schedule the employee never chose.
    """
    _validate_windows(windows)

    for existing in get_weekly(db, employee):
        db.delete(existing)
    db.flush()

    for day, start, end in sorted(windows):
        db.add(
            EmployeeAvailability(
                organization_id=employee.organization_id,
                employee_id=employee.id,
                day_of_week=day,
                start_time=start,
                end_time=end,
            )
        )

    audit.record(
        db,
        organization_id=employee.organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.AVAILABILITY_UPDATED,
        resource_type="employee",
        resource_id=employee.id,
        metadata={"name": employee.user.full_name, "shifts": len(windows)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationFailed(
            "That schedule has duplicate shifts.",
            details={"fields": {"windows": "Each shift on a day must start at a different time."}},
        ) from exc

    return get_weekly(db, employee)


def upsert_override(
    db: Session,
    employee: Employee,
    *,
    date: dt.date,
    available: bool,
    start_time: dt.time | None,
    end_time: dt.time | None,
    reason: str | None,
    actor_user_id: uuid.UUID | None = None,
) -> AvailabilityOverride:
    """Set the override for one date, replacing any existing one.

    Exactly one override per date keeps the precedence rules unambiguous, so this
    is an upsert rather than an append.
    """
    if available:
        if start_time is None or end_time is None:
            raise ValidationFailed(
                "Give the hours available on that date.",
                details={"fields": {"start_time": "Required for special availability."}},
            )
        if end_time <= start_time:
            raise ValidationFailed(
                "The end time has to be after the start time.",
                details={"fields": {"end_time": "Must be later than the start time."}},
            )
    else:
        start_time = end_time = None

    override = db.scalar(
        select(AvailabilityOverride).where(
            AvailabilityOverride.employee_id == employee.id,
            AvailabilityOverride.date == date,
        )
    )
    if override is None:
        override = AvailabilityOverride(
            organization_id=employee.organization_id,
            employee_id=employee.id,
            date=date,
        )
        db.add(override)

    override.available = available
    override.start_time = start_time
    override.end_time = end_time
    override.reason = reason

    audit.record(
        db,
        organization_id=employee.organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.AVAILABILITY_OVERRIDE_SET,
        resource_type="employee",
        resource_id=employee.id,
        metadata={
            "name": employee.user.full_name,
            "date": date.isoformat(),
            "available": available,
        },
    )
    db.commit()
    db.refresh(override)
    return override


def delete_override(
    db: Session,
    employee: Employee,
    override_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    override = db.scalar(
        select(AvailabilityOverride).where(
            AvailabilityOverride.id == override_id,
            AvailabilityOverride.employee_id == employee.id,
        )
    )
    if override is None:
        raise NotFound("We couldn't find that override.")
    audit.record(
        db,
        organization_id=employee.organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.AVAILABILITY_OVERRIDE_REMOVED,
        resource_type="employee",
        resource_id=employee.id,
        metadata={"name": employee.user.full_name, "date": override.date.isoformat()},
    )
    db.delete(override)
    db.commit()
