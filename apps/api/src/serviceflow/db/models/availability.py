from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.employee import Employee

# Weekday numbering follows Python's date.weekday(): Monday is 0, Sunday is 6.
MONDAY = 0
SUNDAY = 6


class EmployeeAvailability(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """One recurring window of a weekly schedule (PRD 10).

    Times are local wall-clock in the organization's timezone, not UTC: "Maria
    works 9am-5pm" stays true across a daylight-saving change, which it would not
    if the window were pinned to an absolute offset.

    Several rows may share a day, which is how split shifts are expressed
    (09:00-12:00 and 13:00-17:00).
    """

    __tablename__ = "employee_availability"
    __table_args__ = (
        UniqueConstraint("employee_id", "day_of_week", "start_time"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week_valid"),
        CheckConstraint("end_time > start_time", name="window_ordered"),
        Index("ix_employee_availability_employee_id_day", "employee_id", "day_of_week"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="availability")


class AvailabilityOverride(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A single date that departs from the weekly schedule (PRD 10).

    Exactly one override may exist per employee per date, which keeps precedence
    unambiguous:

      - `available = false`  -> the date is blocked outright (holiday, sick day)
      - `available = true`   -> start_time/end_time *replace* the weekly windows
      - no row for the date  -> the weekly schedule applies

    A `available = true` row therefore never adds to the weekly hours; it stands
    in for them.
    """

    __tablename__ = "availability_overrides"
    __table_args__ = (
        UniqueConstraint("employee_id", "date"),
        CheckConstraint(
            "(available AND start_time IS NOT NULL AND end_time IS NOT NULL"
            " AND end_time > start_time)"
            " OR (NOT available AND start_time IS NULL AND end_time IS NULL)",
            name="window_matches_availability",
        ),
        Index("ix_availability_overrides_employee_id_date", "employee_id", "date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)
    reason: Mapped[str | None] = mapped_column(String(200))

    employee: Mapped[Employee] = relationship(back_populates="availability_overrides")
