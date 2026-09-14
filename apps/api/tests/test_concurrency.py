"""Concurrent assignment must never double-book an employee (PRD 9, 52).

The race these exist to close:

    Request A checks the employee  -> free
    Request B checks the employee  -> free
    A writes its job
    B writes an overlapping job

Real threads against real PostgreSQL. Nothing here is mocked: the advisory lock
and the exclusion constraint are exercised as they ship, because a test that
stubbed either would prove nothing about the deployed system.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_job,
    make_user,
)

pytestmark = pytest.mark.concurrency

UTC = dt.UTC
BASE = dt.datetime(2027, 4, 5, 10, 0, tzinfo=UTC)


def at(offset_hours: float) -> dt.datetime:
    return BASE + dt.timedelta(hours=offset_hours)


def _fire_together(calls: list) -> list:  # type: ignore[type-arg]
    """Run every call at once, released from a shared barrier.

    The barrier matters: without it the threads start far enough apart that the
    first transaction commits before the second begins, and the race the test
    exists to trigger never happens.
    """
    barrier = threading.Barrier(len(calls))

    def run(call):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [future.result(timeout=30) for future in [pool.submit(run, c) for c in calls]]


def _booking_at(db: Session, organization: Organization, setup: dict, start: dt.datetime):  # type: ignore[no-untyped-def]
    booking = make_booking(db, organization, setup["customer"], setup["service"], start=start)
    booking.requested_end = start + dt.timedelta(hours=2)
    db.commit()
    return booking


def _statuses(responses: list) -> Counter:  # type: ignore[type-arg]
    return Counter(response.status_code for response in responses)


# --------------------------------------------------------- the mandatory cases


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_overlapping_assignments_leave_exactly_one_winner(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Two bookings, one employee, overlapping windows, fired at the same instant."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    first = _booking_at(db, organization, setup, at(0))  # 10:00-12:00
    second = _booking_at(db, organization, setup, at(1))  # 11:00-13:00
    payload = {"employee_id": str(setup["employee"].id)}

    responses = _fire_together(
        [
            lambda: client.post(
                f"/api/v1/bookings/{first.id}/confirm", headers=headers, json=payload
            ),
            lambda: client.post(
                f"/api/v1/bookings/{second.id}/confirm", headers=headers, json=payload
            ),
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 1, f"expected one winner, got {counts}"
    assert counts[409] == 1, f"expected one clean rejection, got {counts}"

    losers = [r for r in responses if r.status_code == 409]
    assert losers[0].json()["error"]["code"] == "BOOKING_CONFLICT"

    # And the database holds one job, not two.
    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == 1


@pytest.mark.parametrize("attempt", range(3))
def test_five_simultaneous_overlapping_attempts_still_leave_one(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)
    payload = {"employee_id": str(setup["employee"].id)}

    # Five bookings that all straddle 12:00, so no two of them can coexist.
    bookings = [
        _booking_at(db, organization, setup, at(offset)) for offset in (0, 0.5, 1, 1.5, 0.25)
    ]

    responses = _fire_together(
        [
            (
                lambda b=b: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{b.id}/confirm", headers=headers, json=payload
                )
            )
            for b in bookings
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 1, f"expected exactly one winner, got {counts}"
    assert counts[409] == 4, f"expected four clean rejections, got {counts}"
    assert all(
        r.json()["error"]["code"] == "BOOKING_CONFLICT" for r in responses if r.status_code == 409
    )
    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == 1


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_non_overlapping_assignments_all_succeed(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Serialising must not turn independent work into false conflicts."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)
    payload = {"employee_id": str(setup["employee"].id)}

    # Back-to-back two-hour slots: 06:00, 08:00, 10:00, 12:00.
    bookings = [_booking_at(db, organization, setup, at(offset)) for offset in (-4, -2, 0, 2)]

    responses = _fire_together(
        [
            (
                lambda b=b: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{b.id}/confirm", headers=headers, json=payload
                )
            )
            for b in bookings
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 4, f"adjacent slots should all be assignable, got {counts}"
    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == 4


@pytest.mark.parametrize("attempt", range(3))
def test_two_employees_are_never_serialised_against_each_other(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """The same window for different people is not a conflict."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    headers = auth_headers(client, admin)

    first = _booking_at(db, organization, setup, at(0))
    second = _booking_at(db, organization, setup, at(0))

    responses = _fire_together(
        [
            lambda: client.post(
                f"/api/v1/bookings/{first.id}/confirm",
                headers=headers,
                json={"employee_id": str(setup["employee"].id)},
            ),
            lambda: client.post(
                f"/api/v1/bookings/{second.id}/confirm",
                headers=headers,
                json={"employee_id": str(colleague.id)},
            ),
        ]
    )
    assert _statuses(responses)[200] == 2


@pytest.mark.parametrize("attempt", range(3))
def test_confirming_the_same_booking_twice_at_once_creates_one_job(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """The phase 3 guarantee, re-checked under real contention."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)
    booking = _booking_at(db, organization, setup, at(0))
    payload = {"employee_id": str(setup["employee"].id)}

    responses = _fire_together(
        [
            (
                lambda: client.post(
                    f"/api/v1/bookings/{booking.id}/confirm", headers=headers, json=payload
                )
            )
            for _ in range(4)
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 1, f"expected one confirmation, got {counts}"
    assert db.query(Job).filter_by(booking_id=booking.id).count() == 1


# --------------------------------------------------------- reassign / reschedule


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_reassignment_onto_one_employee_conflicts_cleanly(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Two overlapping jobs both moved onto the same free technician at once."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    target = make_employee(
        db, organization, email="target@example.com", services=[setup["service"]]
    )
    holder_a = make_employee(
        db, organization, email="holder-a@example.com", services=[setup["service"]]
    )
    holder_b = make_employee(
        db, organization, email="holder-b@example.com", services=[setup["service"]]
    )
    headers = auth_headers(client, admin)

    jobs = []
    for offset, holder in ((0, holder_a), (1, holder_b)):
        booking = _booking_at(db, organization, setup, at(offset))
        booking.status = BookingStatus.CONFIRMED
        db.commit()
        job = make_job(db, organization, booking, holder)
        job.scheduled_start = booking.requested_start
        job.scheduled_end = booking.requested_end
        db.commit()
        jobs.append(job)

    responses = _fire_together(
        [
            (
                lambda j=j: client.post(  # type: ignore[misc]
                    f"/api/v1/jobs/{j.id}/assign",
                    headers=headers,
                    json={"employee_id": str(target.id)},
                )
            )
            for j in jobs
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 1, f"expected one reassignment to win, got {counts}"
    assert counts[409] == 1
    assert db.query(Job).filter_by(employee_id=target.id).count() == 1


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_reschedules_into_one_slot_conflict_cleanly(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Two of an employee's jobs moved onto the same window at the same moment."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    bookings = []
    for offset in (-6, -3):
        booking = _booking_at(db, organization, setup, at(offset))
        booking.status = BookingStatus.CONFIRMED
        db.commit()
        job = make_job(db, organization, booking, setup["employee"])
        job.scheduled_start = booking.requested_start
        job.scheduled_end = booking.requested_end
        db.commit()
        bookings.append(booking)

    target = at(0).isoformat()
    responses = _fire_together(
        [
            (
                lambda b=b: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{b.id}/reschedule",
                    headers=headers,
                    json={"requested_start": target},
                )
            )
            for b in bookings
        ]
    )

    counts = _statuses(responses)
    assert counts[200] == 1, f"expected one reschedule to win, got {counts}"
    assert counts[409] == 1

    # The request threads wrote in their own sessions; drop this one's cache
    # before reading, or the identity map serves pre-reschedule values.
    db.expire_all()
    moved = [
        job
        for job in db.query(Job).filter_by(employee_id=setup["employee"].id).all()
        if job.scheduled_start == at(0)
    ]
    assert len(moved) == 1


def test_the_winner_is_a_real_assignment_not_a_partial_write(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Whichever request wins must leave a fully consistent booking and job."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)
    payload = {"employee_id": str(setup["employee"].id)}

    first = _booking_at(db, organization, setup, at(0))
    second = _booking_at(db, organization, setup, at(1))

    responses = _fire_together(
        [
            (
                lambda b=b: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{b.id}/confirm", headers=headers, json=payload
                )
            )
            for b in (first, second)
        ]
    )
    winner = next(r for r in responses if r.status_code == 200).json()["data"]

    db.expire_all()
    assert winner["status"] == "CONFIRMED"
    assert winner["job"]["status"] == "SCHEDULED"

    # The loser stayed pending, with no orphan job.
    loser_id = second.id if winner["id"] == str(first.id) else first.id
    from serviceflow.db.models.booking import Booking

    loser = db.get(Booking, loser_id)
    assert loser is not None
    assert loser.status is BookingStatus.PENDING
    assert (
        db.query(Job).filter_by(booking_id=loser_id).filter(Job.employee_id.is_not(None)).count()
        == 0
    )
    assert db.query(Job).filter_by(status=JobStatus.SCHEDULED).count() == 1
