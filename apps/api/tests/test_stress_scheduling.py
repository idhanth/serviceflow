"""Scheduling under sustained contention (PRD 52, phase 8).

`test_concurrency.py` proves the single race closes. This goes wider: many
callers at once, several employees competing, and the operations that reach the
same seam from other directions - reschedule, reassign and cancellation.

Real threads, real PostgreSQL, real advisory locks and the real exclusion
constraint. Nothing here is stubbed, because the thing under test is what the
database does when two transactions collide.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_user,
)

pytestmark = [pytest.mark.concurrency, pytest.mark.stress]

UTC = dt.UTC
# Everything stays inside one working day. The fixture makes the employee
# available 00:00-23:59 on this date, so a window that runs past midnight is
# correctly refused as outside working hours - which would be a test that
# failed for the wrong reason.
BASE = dt.datetime(2027, 6, 8, 8, 0, tzinfo=UTC)


def at(hours: float) -> dt.datetime:
    return BASE + dt.timedelta(hours=hours)


def fire_together(calls: list[Any], timeout: float = 45.0) -> list[Any]:
    """Release every call from one barrier, so the collision actually happens."""
    barrier = threading.Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait(timeout=20)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=timeout) for f in [pool.submit(run, c) for c in calls]]


def statuses(responses: list[Any]) -> Counter[int]:
    return Counter(response.status_code for response in responses)


def booking_at(
    db: Session,
    organization: Organization,
    setup: dict[str, Any],
    start: dt.datetime,
    hours: float = 2,
):  # type: ignore[no-untyped-def]
    booking = make_booking(db, organization, setup["customer"], setup["service"], start=start)
    booking.requested_end = start + dt.timedelta(hours=hours)
    db.commit()
    return booking


def no_overlaps(db: Session) -> bool:
    """The invariant, asked of the database rather than of the application."""
    overlapping = db.execute(
        select(func.count())
        .select_from(Job)
        .join(
            Job.__table__.alias("other"),
            Job.employee_id == Job.__table__.alias("other").c.employee_id,
        )
    )
    overlapping.close()
    rows = db.execute(
        select(func.count()).select_from(
            select(Job.id)
            .join(
                Job.__table__.alias("o"),
                (Job.employee_id == Job.__table__.alias("o").c.employee_id)
                & (Job.id != Job.__table__.alias("o").c.id)
                & (Job.scheduled_start < Job.__table__.alias("o").c.scheduled_end)
                & (Job.scheduled_end > Job.__table__.alias("o").c.scheduled_start),
            )
            .subquery()
        )
    ).scalar_one()
    return rows == 0


# ------------------------------------------------------------------ many at once


@pytest.mark.parametrize("attempt", range(3))
def test_twelve_simultaneous_overlapping_confirmations_leave_exactly_one(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """One employee, twelve overlapping bookings, all confirmed at the same instant."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    # Six minutes apart with two-hour windows: every pair genuinely overlaps, so
    # exactly one can be placed. (Spaced further apart, several of them would
    # legitimately fit, and the product would be right to accept them.)
    bookings = [booking_at(db, organization, setup, at(index * 0.1)) for index in range(12)]
    payload = {"employee_id": str(setup["employee"].id)}

    responses = fire_together(
        [
            (
                lambda booking=booking: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{booking.id}/confirm", headers=headers, json=payload
                )
            )
            for booking in bookings
        ]
    )

    counts = statuses(responses)
    assert counts[200] == 1, f"expected exactly one winner, got {counts}"
    assert counts[409] == 11, f"expected eleven clean refusals, got {counts}"
    for response in responses:
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "BOOKING_CONFLICT"

    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == 1
    assert no_overlaps(db)


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_adjacent_confirmations_all_succeed(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Adjacent is not overlapping, however many arrive at once."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    # Six back-to-back jobs at the service's own two-hour duration: 08:00 to
    # 20:00, all inside the day this employee is available. Twelve would run
    # past midnight, which the product correctly refuses as outside hours.
    bookings = [booking_at(db, organization, setup, at(index * 2)) for index in range(6)]
    payload = {"employee_id": str(setup["employee"].id)}

    responses = fire_together(
        [
            (
                lambda booking=booking: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{booking.id}/confirm", headers=headers, json=payload
                )
            )
            for booking in bookings
        ]
    )

    counts = statuses(responses)
    refusals = [r.json()["error"]["message"] for r in responses if r.status_code == 409]
    assert counts[200] == 6, f"back-to-back work must all be assignable, got {counts}: {refusals}"
    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == 6
    assert no_overlaps(db)


@pytest.mark.parametrize("attempt", range(3))
def test_contention_across_several_employees_fills_every_slot_once(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Four employees, twelve overlapping bookings, everyone bidding at once.

    Exactly four can be placed - one per employee - and the database must end
    up with four jobs and no overlap, whichever way the race resolves.
    """
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    employees = [setup["employee"]] + [
        make_employee(
            db, organization, services=[setup["service"]], email=f"tech{index}@example.com"
        )
        for index in range(3)
    ]
    bookings = [booking_at(db, organization, setup, at(index * 0.1)) for index in range(12)]

    calls = []
    for index, booking in enumerate(bookings):
        employee = employees[index % len(employees)]
        calls.append(
            lambda booking=booking, employee=employee: client.post(  # type: ignore[misc]
                f"/api/v1/bookings/{booking.id}/confirm",
                headers=headers,
                json={"employee_id": str(employee.id)},
            )
        )

    responses = fire_together(calls)
    counts = statuses(responses)
    assert counts[200] == len(employees), f"one slot per employee, got {counts}"
    assert counts[409] == len(bookings) - len(employees), counts
    assert db.query(Job).filter(Job.employee_id.is_not(None)).count() == len(employees)
    assert no_overlaps(db)


# ------------------------------------------------------- the other ways in


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_reassignments_onto_one_employee_leave_no_overlap(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Several jobs, all reassigned onto the same person at the same instant."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    crowd = [
        make_employee(
            db, organization, services=[setup["service"]], email=f"from{index}@example.com"
        )
        for index in range(6)
    ]
    jobs = []
    for index, employee in enumerate(crowd):
        # Mutually overlapping, so only one of them can end up on the target.
        booking = booking_at(db, organization, setup, at(index * 0.1))
        response = client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=headers,
            json={"employee_id": str(employee.id)},
        )
        assert response.status_code == 200, response.text
        jobs.append(response.json()["data"]["job"]["id"])

    target = str(setup["employee"].id)
    responses = fire_together(
        [
            (
                lambda job_id=job_id: client.post(  # type: ignore[misc]
                    f"/api/v1/jobs/{job_id}/assign",
                    headers=headers,
                    json={"employee_id": target},
                )
            )
            for job_id in jobs
        ]
    )

    counts = statuses(responses)
    assert counts[200] == 1, f"only one overlapping job can move, got {counts}"
    assert no_overlaps(db)


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_reschedules_into_one_slot_leave_no_overlap(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Every job tries to move into the same free hour at once."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    bookings = []
    for index in range(5):
        # An hour apart, 45 minutes each: five jobs one person can really hold.
        booking = booking_at(db, organization, setup, at(index), hours=0.75)
        response = client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=headers,
            json={"employee_id": str(setup["employee"].id)},
        )
        assert response.status_code == 200, response.text
        bookings.append(booking)

    # A free hour later the same day, which they all try to move into.
    target = at(9).isoformat()
    responses = fire_together(
        [
            (
                lambda booking=booking: client.post(  # type: ignore[misc]
                    f"/api/v1/bookings/{booking.id}/reschedule",
                    headers=headers,
                    json={"requested_start": target},
                )
            )
            for booking in bookings
        ]
    )

    counts = statuses(responses)
    assert counts[200] == 1, f"one job can occupy the slot, got {counts}"
    assert no_overlaps(db)
    assert db.query(Job).filter_by(employee_id=setup["employee"].id).count() == len(bookings)


@pytest.mark.parametrize("attempt", range(3))
def test_a_cancellation_racing_a_confirmation_never_leaves_a_job_on_a_dead_booking(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Cancel and confirm the same booking at once.

    Either outcome is acceptable; a cancelled booking still holding an active
    job is not.
    """
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)
    booking = booking_at(db, organization, setup, at(0))

    responses = fire_together(
        [
            lambda: client.post(
                f"/api/v1/bookings/{booking.id}/confirm",
                headers=headers,
                json={"employee_id": str(setup["employee"].id)},
            ),
            lambda: client.post(f"/api/v1/bookings/{booking.id}/cancel", headers=headers, json={}),
        ]
    )

    assert {response.status_code for response in responses} <= {200, 409}
    db.expire_all()
    stored = db.get(type(booking), booking.id)
    assert stored is not None
    job = db.query(Job).filter_by(booking_id=booking.id).one_or_none()

    if stored.status is BookingStatus.CANCELLED:
        assert job is None or job.status is JobStatus.CANCELLED, (
            "a cancelled booking must not keep live work"
        )
    else:
        assert stored.status is BookingStatus.CONFIRMED
        assert job is not None and job.status is JobStatus.SCHEDULED
    assert no_overlaps(db)
