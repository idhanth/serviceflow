"""Pure availability and overlap semantics - no database, no HTTP."""

from __future__ import annotations

import datetime as dt

import pytest

from serviceflow.services.availability import (
    DateOverride,
    WeeklyWindow,
    Window,
    evaluate_window,
    local_segments,
    merge,
    windows_for_date,
)

UTC = dt.UTC
# 2026-09-07 is a Monday, which keeps weekday arithmetic in these tests obvious.
MONDAY = dt.date(2026, 9, 7)


def at(hour: int, minute: int = 0, day: dt.date = MONDAY) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=UTC)


def nine_to_five(*days: int) -> list[WeeklyWindow]:
    return [WeeklyWindow(d, dt.time(9, 0), dt.time(17, 0)) for d in days]


# ------------------------------------------------------------------ windows


def test_weekly_schedule_applies_to_its_weekday() -> None:
    weekly = nine_to_five(0)  # Mondays only
    assert windows_for_date(MONDAY, weekly, None) == [Window(540, 1020)]
    assert windows_for_date(MONDAY + dt.timedelta(days=1), weekly, None) == []


def test_split_shifts_are_kept_separate_then_merged_only_when_touching() -> None:
    weekly = [
        WeeklyWindow(0, dt.time(9, 0), dt.time(12, 0)),
        WeeklyWindow(0, dt.time(13, 0), dt.time(17, 0)),
    ]
    windows = windows_for_date(MONDAY, weekly, None)
    assert windows == [Window(540, 720), Window(780, 1020)]
    # The lunch gap is real, so merging must not close it.
    assert merge(windows) == [Window(540, 720), Window(780, 1020)]

    touching = merge([Window(540, 720), Window(720, 1020)])
    assert touching == [Window(540, 1020)]


def test_unavailable_override_blocks_the_date_entirely() -> None:
    weekly = nine_to_five(0)
    override = DateOverride(date=MONDAY, available=False, reason="Vacation")
    assert windows_for_date(MONDAY, weekly, override) == []


def test_special_availability_override_replaces_the_weekly_schedule() -> None:
    """It stands in for the normal hours rather than adding to them."""
    weekly = nine_to_five(0)
    override = DateOverride(
        date=MONDAY, available=True, start_time=dt.time(18, 0), end_time=dt.time(21, 0)
    )
    assert windows_for_date(MONDAY, weekly, override) == [Window(1080, 1260)]


def test_an_override_on_another_date_does_not_leak() -> None:
    """Monday being blocked must not affect Tuesday's normal schedule."""
    weekly = nine_to_five(0, 1)
    tuesday = MONDAY + dt.timedelta(days=1)
    overrides = {MONDAY: DateOverride(date=MONDAY, available=False)}

    assert windows_for_date(tuesday, weekly, overrides.get(tuesday)) == [Window(540, 1020)]
    assert evaluate_window(
        at(10, day=tuesday),
        at(12, day=tuesday),
        timezone="UTC",
        weekly=weekly,
        overrides=overrides,
    ).available


# ------------------------------------------------------------------ evaluation


def evaluate(start: dt.datetime, end: dt.datetime, weekly, overrides=None, tz="UTC"):  # type: ignore[no-untyped-def]
    return evaluate_window(start, end, timezone=tz, weekly=weekly, overrides=overrides or {})


def test_a_window_inside_working_hours_is_available() -> None:
    assert evaluate(at(10), at(12), nine_to_five(0)).available


def test_boundaries_are_inclusive_of_the_shift_edges() -> None:
    assert evaluate(at(9), at(17), nine_to_five(0)).available


@pytest.mark.parametrize(
    ("start", "end"),
    [(at(8), at(10)), (at(16), at(18)), (at(7), at(8)), (at(18), at(19))],
)
def test_windows_outside_working_hours_are_refused(start: dt.datetime, end: dt.datetime) -> None:
    verdict = evaluate(start, end, nine_to_five(0))
    assert verdict.blocked
    assert "Outside working hours" in (verdict.reason or "")


def test_a_day_with_no_shift_says_so() -> None:
    verdict = evaluate(at(10), at(12), nine_to_five(1))  # Tuesdays only
    assert verdict.blocked
    assert verdict.reason == "Doesn't work Mondays."


def test_an_unavailable_override_names_its_reason() -> None:
    overrides = {MONDAY: DateOverride(date=MONDAY, available=False, reason="Vacation")}
    verdict = evaluate(at(10), at(12), nine_to_five(0), overrides)
    assert verdict.blocked
    assert "Vacation" in (verdict.reason or "")


def test_a_special_availability_override_grants_hours_the_week_does_not() -> None:
    overrides = {
        MONDAY: DateOverride(
            date=MONDAY, available=True, start_time=dt.time(18, 0), end_time=dt.time(22, 0)
        )
    }
    assert evaluate(at(19), at(21), nine_to_five(0), overrides).available
    # ...and withdraws the hours the weekly schedule would have given.
    assert evaluate(at(10), at(12), nine_to_five(0), overrides).blocked


def test_a_lunch_gap_is_not_bookable_through() -> None:
    weekly = [
        WeeklyWindow(0, dt.time(9, 0), dt.time(12, 0)),
        WeeklyWindow(0, dt.time(13, 0), dt.time(17, 0)),
    ]
    assert evaluate(at(9), at(11), weekly).available
    assert evaluate(at(13, 30), at(16), weekly).available
    # Straddling the break needs hours that do not exist.
    assert evaluate(at(11), at(14), weekly).blocked


# ------------------------------------------------------------------ timezones


def test_availability_is_evaluated_in_the_organization_timezone() -> None:
    """09:00-17:00 in Los Angeles is 16:00-00:00 UTC, not 09:00-17:00 UTC."""
    weekly = nine_to_five(0)
    tz = "America/Los_Angeles"

    # 10:00 local on Monday = 17:00 UTC.
    assert evaluate(at(17), at(19), weekly, tz=tz).available
    # 10:00 UTC is 03:00 local - still Monday, but long before the shift.
    assert evaluate(at(10), at(12), weekly, tz=tz).blocked


def test_a_utc_instant_can_fall_on_a_different_local_weekday() -> None:
    """01:00 UTC Tuesday is 18:00 Monday in Los Angeles."""
    tz = "America/Los_Angeles"
    weekly = [WeeklyWindow(0, dt.time(17, 0), dt.time(20, 0))]  # Monday evening
    tuesday_utc = dt.datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
    assert evaluate(tuesday_utc, tuesday_utc + dt.timedelta(hours=1), weekly, tz=tz).available


def test_local_wall_clock_hours_survive_a_daylight_saving_change() -> None:
    """The shift stays 9-5 local; the UTC offset behind it shifts by an hour."""
    tz = "America/New_York"
    weekly = [WeeklyWindow(day, dt.time(9, 0), dt.time(17, 0)) for day in range(7)]

    # 1 Nov 2026 is after the US DST end, 1 Oct 2026 is before it.
    summer = dt.datetime(2026, 10, 1, 14, 0, tzinfo=UTC)  # 10:00 EDT
    winter = dt.datetime(2026, 11, 5, 15, 0, tzinfo=UTC)  # 10:00 EST

    assert evaluate(summer, summer + dt.timedelta(hours=2), weekly, tz=tz).available
    assert evaluate(winter, winter + dt.timedelta(hours=2), weekly, tz=tz).available

    # The same UTC instant that was mid-shift in summer is pre-shift in winter.
    early_winter = dt.datetime(2026, 11, 5, 13, 0, tzinfo=UTC)  # 08:00 EST
    assert evaluate(early_winter, early_winter + dt.timedelta(hours=1), weekly, tz=tz).blocked


def test_an_interval_crossing_local_midnight_splits_per_date() -> None:
    tz = "UTC"
    segments = local_segments(at(22), at(22) + dt.timedelta(hours=4), dt.UTC)  # type: ignore[arg-type]
    assert [(s.date, s.start, s.end) for s in segments] == [
        (MONDAY, 1320, 1440),
        (MONDAY + dt.timedelta(days=1), 0, 120),
    ]
    # A day-bounded schedule cannot cover the part after midnight.
    weekly = [WeeklyWindow(d, dt.time(0, 0), dt.time(23, 59)) for d in range(7)]
    assert evaluate(at(22), at(22) + dt.timedelta(hours=4), weekly, tz=tz).blocked
