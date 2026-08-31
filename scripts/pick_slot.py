"""Choose a slot the demo technician can actually take.

The smoke test books a real appointment against a real calendar, so a hardcoded
time collides with whatever the seed or a previous run already put there. This
reads the technician's weekly availability and their booked work, and returns
the first opening wide enough for the service - all evaluated in the
organization's timezone, which is the only timezone the scheduler uses.

    pick_slot.py <timezone> <duration_minutes> <availability.json> <calendar.json>

Prints one UTC instant in ISO-8601, or exits non-zero if there is no opening.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

SEARCH_DAYS = 21
STEP = dt.timedelta(minutes=30)


def main() -> int:
    timezone, duration_raw, availability_path, calendar_path = sys.argv[1:5]
    tz = ZoneInfo(timezone)
    duration = dt.timedelta(minutes=int(duration_raw))

    with open(availability_path) as handle:
        availability = json.load(handle)["data"]
    weekly: dict[int, list[tuple[dt.time, dt.time]]] = {}
    for window in availability["weekly"]:
        weekly.setdefault(window["day_of_week"], []).append(
            (dt.time.fromisoformat(window["start_time"]), dt.time.fromisoformat(window["end_time"]))
        )

    blocked_days = {
        dt.date.fromisoformat(o["date"]) for o in availability["overrides"] if not o["available"]
    }

    with open(calendar_path) as handle:
        busy = [
            (
                dt.datetime.fromisoformat(event["scheduled_start"].replace("Z", "+00:00")),
                dt.datetime.fromisoformat(event["scheduled_end"].replace("Z", "+00:00")),
            )
            for event in json.load(handle)["data"]
        ]

    # Start tomorrow: today's remaining hours are the most contended, and a
    # same-day booking is not what the demo is showing off anyway.
    today = dt.datetime.now(tz).date()
    for offset in range(1, SEARCH_DAYS + 1):
        day = today + dt.timedelta(days=offset)
        if day in blocked_days:
            continue
        for window_start, window_end in sorted(weekly.get(day.weekday(), [])):
            opens = dt.datetime.combine(day, window_start, tzinfo=tz)
            closes = dt.datetime.combine(day, window_end, tzinfo=tz)
            candidate = opens
            while candidate + duration <= closes:
                finish = candidate + duration
                if not any(start < finish and candidate < end for start, end in busy):
                    print(candidate.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"))
                    return 0
                candidate += STEP

    print(
        f"no {duration.total_seconds() // 60:.0f}-minute opening for this technician "
        f"in the next {SEARCH_DAYS} days",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
