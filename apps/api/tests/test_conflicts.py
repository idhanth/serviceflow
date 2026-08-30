"""Overlap detection against the database (PRD 9)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.organization import Organization
from serviceflow.services.conflicts import overlapping_jobs
from tests.conftest import booking_setup, make_booking, make_job

UTC = dt.UTC
BASE = dt.datetime(2027, 3, 1, 10, 0, tzinfo=UTC)


def hours(offset: float) -> dt.datetime:
    return BASE + dt.timedelta(hours=offset)


def _job_at(
    db: Session, organization: Organization, setup: dict, start, end, status=JobStatus.ASSIGNED
):  # type: ignore[no-untyped-def]
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=start,
        status=BookingStatus.CONFIRMED,
    )
    booking.requested_end = end
    db.commit()
    job = make_job(db, organization, booking, setup["employee"], status=status)
    job.scheduled_start = start
    job.scheduled_end = end
    db.commit()
    return job


def find(db: Session, organization: Organization, setup: dict, start, end, exclude=None):  # type: ignore[no-untyped-def]
    return overlapping_jobs(
        db,
        organization_id=organization.id,
        employee_id=setup["employee"].id,
        start=start,
        end=end,
        exclude_job_id=exclude,
    )


@pytest.mark.parametrize(
    ("start", "end", "expected", "label"),
    [
        (hours(0), hours(2), True, "identical"),
        (hours(0.5), hours(1.5), True, "fully contained"),
        (hours(-1), hours(3), True, "fully containing"),
        (hours(1), hours(3), True, "partial overlap at the end"),
        (hours(-1), hours(1), True, "partial overlap at the start"),
        (hours(2), hours(4), False, "adjacent immediately after"),
        (hours(-2), hours(0), False, "adjacent immediately before"),
        (hours(3), hours(4), False, "clearly after"),
        (hours(-4), hours(-3), False, "clearly before"),
    ],
)
def test_overlap_rule(
    db: Session,
    organization: Organization,
    start: dt.datetime,
    end: dt.datetime,
    expected: bool,
    label: str,
) -> None:
    """new_start < existing_end AND new_end > existing_start, against 10:00-12:00."""
    setup = booking_setup(db, organization)
    _job_at(db, organization, setup, hours(0), hours(2))
    assert bool(find(db, organization, setup, start, end)) is expected, label


def test_adjacent_appointments_are_explicitly_allowed(
    db: Session, organization: Organization
) -> None:
    """10:00-12:00 and 12:00-14:00 must coexist, in the query and in the database."""
    setup = booking_setup(db, organization)
    _job_at(db, organization, setup, hours(0), hours(2))
    assert find(db, organization, setup, hours(2), hours(4)) == []

    # And the exclusion constraint agrees - this insert must not raise.
    second = _job_at(db, organization, setup, hours(2), hours(4))
    assert second.id is not None


def test_a_cancelled_job_frees_its_slot(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    _job_at(db, organization, setup, hours(0), hours(2), status=JobStatus.CANCELLED)
    assert find(db, organization, setup, hours(0), hours(2)) == []


def test_a_completed_job_still_blocks(db: Session, organization: Organization) -> None:
    """That time really was spent, so it is not free to reassign."""
    setup = booking_setup(db, organization)
    _job_at(db, organization, setup, hours(0), hours(2), status=JobStatus.COMPLETED)
    assert len(find(db, organization, setup, hours(1), hours(3))) == 1


def test_excluding_a_job_stops_it_conflicting_with_itself(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    job = _job_at(db, organization, setup, hours(0), hours(2))
    assert find(db, organization, setup, hours(0), hours(2)) != []
    assert find(db, organization, setup, hours(0), hours(2), exclude=job.id) == []


def test_another_employees_job_is_not_a_conflict(db: Session, organization: Organization) -> None:
    from tests.conftest import make_employee

    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=hours(0),
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, booking, colleague)

    assert find(db, organization, setup, hours(0), hours(2)) == []


def test_the_database_refuses_an_overlap_even_without_the_service_layer(
    db: Session, organization: Organization
) -> None:
    """The exclusion constraint is the backstop, not just the query."""
    from sqlalchemy.exc import IntegrityError

    from serviceflow.services.conflicts import is_overlap_violation

    setup = booking_setup(db, organization)
    _job_at(db, organization, setup, hours(0), hours(2))

    with pytest.raises(IntegrityError) as raised:
        _job_at(db, organization, setup, hours(1), hours(3))
    assert is_overlap_violation(raised.value)
    db.rollback()
