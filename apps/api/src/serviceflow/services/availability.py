"""Evaluating whether a time window falls inside an employee's working hours.

Availability is stored as local wall-clock times in the organization's timezone
(PRD 10, 40), while jobs are stored as absolute UTC instants. Everything here
converts one to the other explicitly, so a daylight-saving change moves the
absolute instant an employee starts work without editing their schedule.

The core of this module is pure: `windows_for_date` and `evaluate_window` take
plain data and return plain data, which is what makes the semantics testable
without a database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

MINUTES_PER_DAY = 24 * 60

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def minutes_of(value: dt.time) -> int:
    return value.hour * 60 + value.minute


@dataclass(frozen=True, slots=True)
class Window:
    """A local wall-clock window, as minutes from midnight."""

    start: int
    end: int

    def covers(self, start: int, end: int) -> bool:
        return self.start <= start and self.end >= end


@dataclass(frozen=True, slots=True)
class WeeklyWindow:
    day_of_week: int
    start_time: dt.time
    end_time: dt.time


@dataclass(frozen=True, slots=True)
class DateOverride:
    date: dt.date
    available: bool
    start_time: dt.time | None = None
    end_time: dt.time | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityVerdict:
    available: bool
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.available


@dataclass(frozen=True, slots=True)
class LocalSegment:
    """The part of an interval that falls on one local calendar date."""

    date: dt.date
    start: int
    end: int


def windows_for_date(
    date: dt.date,
    weekly: list[WeeklyWindow],
    override: DateOverride | None,
) -> list[Window]:
    """Resolve the working windows for one local date.

    Precedence (PRD 10):
      1. an override marked unavailable blocks the date outright;
      2. an override marked available *replaces* the weekly schedule for it;
      3. with no override, the weekly schedule for that weekday applies.
    """
    if override is not None:
        if not override.available:
            return []
        if override.start_time is None or override.end_time is None:
            # The check constraint prevents this; treat it as blocked rather than
            # silently granting a whole day.
            return []
        return [Window(minutes_of(override.start_time), minutes_of(override.end_time))]

    return sorted(
        (
            Window(minutes_of(window.start_time), minutes_of(window.end_time))
            for window in weekly
            if window.day_of_week == date.weekday()
        ),
        key=lambda window: window.start,
    )


def merge(windows: list[Window]) -> list[Window]:
    """Coalesce touching or overlapping windows, so a split shift reads as one."""
    merged: list[Window] = []
    for window in sorted(windows, key=lambda w: w.start):
        if merged and window.start <= merged[-1].end:
            merged[-1] = Window(merged[-1].start, max(merged[-1].end, window.end))
        else:
            merged.append(window)
    return merged


def local_segments(start: dt.datetime, end: dt.datetime, tz: ZoneInfo) -> list[LocalSegment]:
    """Split a UTC interval into per-local-date pieces.

    An appointment that crosses local midnight yields one segment per date, each
    of which has to be covered on its own.
    """
    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)

    segments: list[LocalSegment] = []
    cursor = start_local
    while cursor < end_local:
        day = cursor.date()
        next_midnight = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
        segment_end = min(end_local, next_midnight)

        start_minutes = cursor.hour * 60 + cursor.minute
        end_minutes = (
            MINUTES_PER_DAY
            if segment_end == next_midnight
            else segment_end.hour * 60 + segment_end.minute
        )
        segments.append(LocalSegment(date=day, start=start_minutes, end=end_minutes))
        cursor = segment_end
    return segments


def _format(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    suffix = "am" if hour < 12 else "pm"
    display = hour % 12 or 12
    return f"{display}:{minute:02d}{suffix}"


def evaluate_window(
    start: dt.datetime,
    end: dt.datetime,
    *,
    timezone: str,
    weekly: list[WeeklyWindow],
    overrides: dict[dt.date, DateOverride],
) -> AvailabilityVerdict:
    """Decide whether a UTC interval sits entirely inside working hours."""
    tz = ZoneInfo(timezone)
    segments = local_segments(start, end, tz)
    if not segments:
        return AvailabilityVerdict(available=False, reason="That time range is empty.")

    for segment in segments:
        override = overrides.get(segment.date)
        windows = merge(windows_for_date(segment.date, weekly, override))

        if not windows:
            if override is not None and not override.available:
                detail = f" ({override.reason})" if override.reason else ""
                return AvailabilityVerdict(
                    available=False,
                    reason=f"Unavailable on {segment.date:%b %-d}{detail}.",
                )
            return AvailabilityVerdict(
                available=False,
                reason=f"Doesn't work {WEEKDAY_NAMES[segment.date.weekday()]}s.",
            )

        if not any(window.covers(segment.start, segment.end) for window in windows):
            hours = ", ".join(f"{_format(w.start)}-{_format(w.end)}" for w in windows)
            return AvailabilityVerdict(
                available=False,
                reason=(
                    f"Outside working hours on {segment.date:%b %-d}"
                    f" ({hours}); this needs {_format(segment.start)}-{_format(segment.end)}."
                ),
            )

    return AvailabilityVerdict(available=True)
