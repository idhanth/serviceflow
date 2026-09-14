"""Employee ranking (PRD 11) - deterministic, and explainable from its output."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.organization import Organization
from serviceflow.services.recommendations import EmployeeRecommendation, recommend_employees
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_job,
    make_service,
    make_user,
    set_override,
    set_weekly_availability,
)

UTC = dt.UTC
# A Monday, so weekday 0 is the relevant schedule.
SLOT = dt.datetime(2027, 5, 3, 10, 0, tzinfo=UTC)
SLOT_END = SLOT + dt.timedelta(hours=2)


# ------------------------------------------------------------------ sort key


def test_assignable_candidates_outrank_unavailable_ones() -> None:
    busy_but_free = EmployeeRecommendation(
        employee_id=uuid.UUID(int=1),
        full_name="Zoe",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=9,
        scheduled_minutes_today=900,
    )
    idle_but_off = EmployeeRecommendation(
        employee_id=uuid.UUID(int=2),
        full_name="Aaron",
        job_title="D",
        available=False,
        conflict=False,
        reason="Off",
        jobs_today=0,
        scheduled_minutes_today=0,
    )
    assert sorted([idle_but_off, busy_but_free], key=lambda r: r.sort_key)[0] is busy_but_free


def test_the_lighter_day_wins_among_assignable_candidates() -> None:
    light = EmployeeRecommendation(
        employee_id=uuid.UUID(int=1),
        full_name="Zoe",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=1,
        scheduled_minutes_today=60,
    )
    heavy = EmployeeRecommendation(
        employee_id=uuid.UUID(int=2),
        full_name="Aaron",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=3,
        scheduled_minutes_today=60,
    )
    assert sorted([heavy, light], key=lambda r: r.sort_key)[0] is light


def test_hours_break_a_tie_on_job_count() -> None:
    short = EmployeeRecommendation(
        employee_id=uuid.UUID(int=1),
        full_name="Zoe",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=2,
        scheduled_minutes_today=90,
    )
    long = EmployeeRecommendation(
        employee_id=uuid.UUID(int=2),
        full_name="Aaron",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=2,
        scheduled_minutes_today=400,
    )
    assert sorted([long, short], key=lambda r: r.sort_key)[0] is short


def test_ties_fall_back_to_a_stable_alphabetical_order() -> None:
    """No two candidates may ever compare equal, or the order would wobble."""
    a = EmployeeRecommendation(
        employee_id=uuid.UUID(int=9),
        full_name="Aaron",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=1,
        scheduled_minutes_today=60,
    )
    z = EmployeeRecommendation(
        employee_id=uuid.UUID(int=1),
        full_name="Zoe",
        job_title="D",
        available=True,
        conflict=False,
        reason=None,
        jobs_today=1,
        scheduled_minutes_today=60,
    )
    assert [r.full_name for r in sorted([z, a], key=lambda r: r.sort_key)] == ["Aaron", "Zoe"]
    assert a.sort_key != z.sort_key


def test_conflict_makes_a_candidate_unassignable() -> None:
    clashing = EmployeeRecommendation(
        employee_id=uuid.UUID(int=1),
        full_name="Zoe",
        job_title="D",
        available=True,
        conflict=True,
        reason="Already booked",
        jobs_today=0,
        scheduled_minutes_today=0,
    )
    assert clashing.assignable is False


# ------------------------------------------------------------------ against the db


def test_only_active_qualified_employees_are_considered(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    other = make_service(db, organization, name="Express Wash", duration_minutes=45)
    make_employee(db, organization, email="unqualified@example.com", services=[other])
    make_employee(
        db, organization, email="retired@example.com", services=[setup["service"]], active=False
    )

    ranked = recommend_employees(
        db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
    )
    assert [r.employee_id for r in ranked] == [setup["employee"].id]


def test_an_employee_off_that_weekday_is_ranked_last_with_a_reason(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    weekend_only = make_employee(
        db,
        organization,
        email="weekend@example.com",
        services=[setup["service"]],
        always_available=False,
    )
    set_weekly_availability(db, weekend_only, days=[5, 6], start="09:00", end="17:00")

    ranked = recommend_employees(
        db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
    )
    assert ranked[0].employee_id == setup["employee"].id
    last = ranked[-1]
    assert last.employee_id == weekend_only.id
    assert last.available is False
    assert last.reason == "Doesn't work Mondays."


def test_an_unavailable_override_shows_its_reason(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    set_override(db, setup["employee"], date=SLOT.date(), available=False, reason="Vacation")

    ranked = recommend_employees(
        db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
    )
    assert ranked[0].available is False
    assert "Vacation" in (ranked[0].reason or "")


def test_a_conflicting_job_is_reported_with_the_clashing_time(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=SLOT,
        status=BookingStatus.CONFIRMED,
    )
    booking.requested_end = SLOT_END
    db.commit()
    job = make_job(db, organization, booking, setup["employee"])
    job.scheduled_start, job.scheduled_end = SLOT, SLOT_END
    db.commit()

    ranked = recommend_employees(
        db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
    )
    assert ranked[0].conflict is True
    assert ranked[0].assignable is False
    assert ranked[0].conflicting_job_id == job.id
    assert "Already booked" in (ranked[0].reason or "")


def test_the_least_loaded_technician_is_recommended_first(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    quiet = make_employee(db, organization, email="quiet@example.com", services=[setup["service"]])

    # Give the setup employee two earlier jobs the same day.
    for offset in (-6, -3):
        booking = make_booking(
            db,
            organization,
            setup["customer"],
            setup["service"],
            start=SLOT + dt.timedelta(hours=offset),
            status=BookingStatus.CONFIRMED,
        )
        booking.requested_end = booking.requested_start + dt.timedelta(hours=1)
        db.commit()
        job = make_job(db, organization, booking, setup["employee"])
        job.scheduled_start = booking.requested_start
        job.scheduled_end = booking.requested_end
        db.commit()

    ranked = recommend_employees(
        db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
    )
    assert ranked[0].employee_id == quiet.id
    assert ranked[0].jobs_today == 0
    busy = next(r for r in ranked if r.employee_id == setup["employee"].id)
    assert busy.jobs_today == 2
    assert busy.scheduled_minutes_today == 120


def test_ranking_is_reproducible(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    for index in range(4):
        make_employee(
            db, organization, email=f"tech{index}@example.com", services=[setup["service"]]
        )
    runs = [
        [
            r.employee_id
            for r in recommend_employees(
                db, organization.id, service=setup["service"], start=SLOT, end=SLOT_END
            )
        ]
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)


def test_the_api_exposes_the_ranking_and_its_reasons(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    off_today = make_employee(
        db,
        organization,
        email="off@example.com",
        services=[setup["service"]],
        always_available=False,
    )
    set_weekly_availability(db, off_today, days=[5, 6], start="09:00", end="17:00")

    booking = make_booking(db, organization, setup["customer"], setup["service"], start=SLOT)
    response = client.get(
        f"/api/v1/bookings/{booking.id}/assignable-employees",
        headers=auth_headers(client, admin),
    )
    assert response.status_code == 200
    rows = response.json()["data"]

    assert rows[0]["assignable"] is True
    assert rows[0]["jobs_today"] == 0
    unavailable = next(r for r in rows if r["id"] == str(off_today.id))
    assert unavailable["available"] is False
    assert unavailable["assignable"] is False
    assert unavailable["reason"]
