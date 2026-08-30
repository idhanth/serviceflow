from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability


class WeeklyWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day_of_week: int
    start_time: dt.time
    end_time: dt.time


class WeeklyWindowInput(BaseModel):
    """Weekday numbering matches Python's date.weekday(): Monday 0 ... Sunday 6."""

    day_of_week: int = Field(ge=0, le=6)
    start_time: dt.time
    end_time: dt.time

    @model_validator(mode="after")
    def _ordered(self) -> WeeklyWindowInput:
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after the start time.")
        return self


class WeeklyScheduleUpdate(BaseModel):
    windows: list[WeeklyWindowInput] = Field(default_factory=list, max_length=21)


class OverrideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: dt.date
    available: bool
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    reason: str | None = None


class OverrideInput(BaseModel):
    date: dt.date
    available: bool = False
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    reason: str | None = Field(default=None, max_length=200)


class AvailabilityRead(BaseModel):
    employee_id: uuid.UUID
    full_name: str
    timezone: str
    weekly: list[WeeklyWindowRead]
    overrides: list[OverrideRead]

    @classmethod
    def build(
        cls,
        *,
        employee_id: uuid.UUID,
        full_name: str,
        timezone: str,
        weekly: list[EmployeeAvailability],
        overrides: list[AvailabilityOverride],
    ) -> AvailabilityRead:
        return cls(
            employee_id=employee_id,
            full_name=full_name,
            timezone=timezone,
            weekly=[WeeklyWindowRead.model_validate(w) for w in weekly],
            overrides=[OverrideRead.model_validate(o) for o in overrides],
        )
