"""Weekly schedules and date overrides for the demo employees (PRD 10)."""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.organization import Organization
from serviceflow.db.seed_data import OVERRIDE_SPECS, WEEKLY_SHIFTS

logger = logging.getLogger(__name__)


def _time(value: str) -> dt.time:
    hour, minute = value.split(":")
    return dt.time(int(hour), int(minute))


def seed_availability(db: Session, org: Organization) -> dict[str, int]:
    """Idempotent: keyed on (employee, weekday, start) and (employee, date)."""
    employees = {
        employee.user.email: employee
        for employee in db.scalars(select(Employee).where(Employee.organization_id == org.id))
    }

    windows = 0
    for email, shifts in WEEKLY_SHIFTS.items():
        employee = employees.get(email)
        if employee is None:
            continue
        for shift in shifts:
            for day in shift["days"]:
                shift_start = _time(shift["start"])
                existing_window = db.scalar(
                    select(EmployeeAvailability).where(
                        EmployeeAvailability.employee_id == employee.id,
                        EmployeeAvailability.day_of_week == day,
                        EmployeeAvailability.start_time == shift_start,
                    )
                )
                if existing_window is None:
                    db.add(
                        EmployeeAvailability(
                            organization_id=org.id,
                            employee_id=employee.id,
                            day_of_week=day,
                            start_time=shift_start,
                            end_time=_time(shift["end"]),
                        )
                    )
                    windows += 1

    today = dt.datetime.now(ZoneInfo(org.timezone)).date()
    overrides = 0
    for email, specs in OVERRIDE_SPECS.items():
        employee = employees.get(email)
        if employee is None:
            continue
        for offset, available, start, end, reason in specs:
            date = today + dt.timedelta(days=offset)
            existing_override = db.scalar(
                select(AvailabilityOverride).where(
                    AvailabilityOverride.employee_id == employee.id,
                    AvailabilityOverride.date == date,
                )
            )
            if existing_override is None:
                db.add(
                    AvailabilityOverride(
                        organization_id=org.id,
                        employee_id=employee.id,
                        date=date,
                        available=available,
                        start_time=_time(start) if start else None,
                        end_time=_time(end) if end else None,
                        reason=reason,
                    )
                )
                overrides += 1

    db.flush()
    logger.info("seeded availability", extra={"windows": windows, "overrides": overrides})
    return {"availability_windows": windows, "overrides": overrides}
