"""Availability and conflicts enforced through the booking workflow itself."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_user,
    set_override,
    set_weekly_availability,
)

UTC = dt.UTC
MONDAY = dt.datetime(2027, 6, 7, 10, 0, tzinfo=UTC)  # a Monday


def _pending(db: Session, organization: Organization, setup: dict, start: dt.datetime):  # type: ignore[no-untyped-def]
    booking = make_booking(db, organization, setup["customer"], setup["service"], start=start)
    booking.requested_end = start + dt.timedelta(hours=2)
    db.commit()
    return booking


def _confirm(client: TestClient, headers: dict, booking, employee):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(employee.id)},
    )


def test_confirmation_is_refused_outside_working_hours(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    employee = setup["employee"]

    set_weekly_availability(db, employee, days=[0], start="13:00", end="18:00")
    # Remove the fixture's round-the-clock week so only the 13:00-18:00 shift stands.
    from serviceflow.db.models.availability import EmployeeAvailability

    for row in db.query(EmployeeAvailability).filter_by(employee_id=employee.id).all():
        if row.start_time != dt.time(13, 0):
            db.delete(row)
    db.commit()

    booking = _pending(db, organization, setup, MONDAY)  # 10:00-12:00
    response = _confirm(client, auth_headers(client, admin), booking, employee)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_SCHEDULE"
    assert "Outside working hours" in response.json()["error"]["message"]

    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING
    assert db.query(Job).filter(Job.employee_id.is_not(None)).count() == 0


def test_confirmation_is_refused_on_a_day_off(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    weekend = make_employee(
        db,
        organization,
        email="weekend@example.com",
        services=[setup["service"]],
        always_available=False,
    )
    set_weekly_availability(db, weekend, days=[5, 6], start="09:00", end="17:00")

    booking = _pending(db, organization, setup, MONDAY)
    response = _confirm(client, auth_headers(client, admin), booking, weekend)

    assert response.status_code == 409
    assert "Doesn't work Mondays" in response.json()["error"]["message"]


def test_an_unavailable_override_blocks_an_otherwise_working_day(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    set_override(db, setup["employee"], date=MONDAY.date(), available=False, reason="Training day")

    booking = _pending(db, organization, setup, MONDAY)
    response = _confirm(client, auth_headers(client, admin), booking, setup["employee"])

    assert response.status_code == 409
    assert "Training day" in response.json()["error"]["message"]


def test_a_special_availability_override_permits_hours_the_week_does_not(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    evening = make_employee(
        db,
        organization,
        email="evening@example.com",
        services=[setup["service"]],
        always_available=False,
    )
    set_weekly_availability(db, evening, days=[0], start="09:00", end="12:00")

    late = MONDAY.replace(hour=19)
    booking = _pending(db, organization, setup, late)

    refused = _confirm(client, auth_headers(client, admin), booking, evening)
    assert refused.status_code == 409

    set_override(
        db,
        evening,
        date=late.date(),
        available=True,
        start="18:00",
        end="23:00",
        reason="Covering a late finish",
    )
    accepted = _confirm(client, auth_headers(client, admin), booking, evening)
    assert accepted.status_code == 200
    assert accepted.json()["data"]["job"]["status"] == "SCHEDULED"


def test_a_special_availability_override_also_withdraws_the_normal_hours(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """It replaces the weekly schedule rather than adding to it."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    set_override(
        db, setup["employee"], date=MONDAY.date(), available=True, start="18:00", end="22:00"
    )

    booking = _pending(db, organization, setup, MONDAY)  # 10:00, inside the normal week
    response = _confirm(client, auth_headers(client, admin), booking, setup["employee"])
    assert response.status_code == 409
    assert "Outside working hours" in response.json()["error"]["message"]


def test_a_second_overlapping_assignment_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    first = _pending(db, organization, setup, MONDAY)
    assert _confirm(client, headers, first, setup["employee"]).status_code == 200

    second = _pending(db, organization, setup, MONDAY + dt.timedelta(hours=1))
    response = _confirm(client, headers, second, setup["employee"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOKING_CONFLICT"
    assert "already booked" in response.json()["error"]["message"].lower()
    assert response.json()["error"]["details"]["conflicting_job_id"]

    db.expire_all()
    assert db.query(Job).filter(Job.employee_id.is_not(None)).count() == 1


def test_an_adjacent_assignment_is_accepted(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """10:00-12:00 then 12:00-14:00 is a full day, not a clash."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    first = _pending(db, organization, setup, MONDAY)
    second = _pending(db, organization, setup, MONDAY + dt.timedelta(hours=2))

    assert _confirm(client, headers, first, setup["employee"]).status_code == 200
    assert _confirm(client, headers, second, setup["employee"]).status_code == 200
    assert db.query(Job).count() == 2


def test_cancelling_frees_the_slot_for_someone_else(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    first = _pending(db, organization, setup, MONDAY)
    _confirm(client, headers, first, setup["employee"])
    client.post(f"/api/v1/bookings/{first.id}/cancel", headers=headers, json={})

    second = _pending(db, organization, setup, MONDAY)
    assert _confirm(client, headers, second, setup["employee"]).status_code == 200


def test_rescheduling_onto_a_busy_window_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    occupied = _pending(db, organization, setup, MONDAY)
    _confirm(client, headers, occupied, setup["employee"])

    movable = _pending(db, organization, setup, MONDAY + dt.timedelta(days=1))
    _confirm(client, headers, movable, setup["employee"])

    response = client.post(
        f"/api/v1/bookings/{movable.id}/reschedule",
        headers=headers,
        json={"requested_start": (MONDAY + dt.timedelta(minutes=30)).isoformat()},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOKING_CONFLICT"


def test_rescheduling_a_job_onto_its_own_window_is_not_a_self_conflict(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    booking = _pending(db, organization, setup, MONDAY)
    _confirm(client, headers, booking, setup["employee"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/reschedule",
        headers=headers,
        json={"requested_start": (MONDAY + dt.timedelta(minutes=15)).isoformat()},
    )
    assert response.status_code == 200


def test_reassigning_onto_a_busy_technician_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    headers = auth_headers(client, admin)

    theirs = _pending(db, organization, setup, MONDAY)
    _confirm(client, headers, theirs, colleague)

    mine = _pending(db, organization, setup, MONDAY + dt.timedelta(hours=1))
    confirmed = _confirm(client, headers, mine, setup["employee"])
    job_id = confirmed.json()["data"]["job"]["id"]

    response = client.post(
        f"/api/v1/jobs/{job_id}/assign", headers=headers, json={"employee_id": str(colleague.id)}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BOOKING_CONFLICT"


def test_reassigning_onto_someone_off_that_day_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    weekend = make_employee(
        db,
        organization,
        email="weekend@example.com",
        services=[setup["service"]],
        always_available=False,
    )
    set_weekly_availability(db, weekend, days=[5, 6], start="09:00", end="17:00")
    headers = auth_headers(client, admin)

    booking = _pending(db, organization, setup, MONDAY)
    job_id = _confirm(client, headers, booking, setup["employee"]).json()["data"]["job"]["id"]

    response = client.post(
        f"/api/v1/jobs/{job_id}/assign", headers=headers, json={"employee_id": str(weekend.id)}
    )
    assert response.status_code == 409


def test_availability_is_evaluated_in_the_organizations_timezone(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A 9-5 Los Angeles shift accepts 17:00 UTC and refuses 09:00 UTC."""
    from tests.conftest import make_organization

    la_org = make_organization(db, name="Pacific Detailing")
    la_org.timezone = "America/Los_Angeles"
    db.commit()

    admin = make_user(db, la_org, role=Role.OWNER, email="pacific-admin@example.com")
    setup = booking_setup(db, la_org)
    employee = setup["employee"]

    from serviceflow.db.models.availability import EmployeeAvailability

    db.query(EmployeeAvailability).filter_by(employee_id=employee.id).delete()
    db.commit()
    set_weekly_availability(db, employee, days=list(range(7)), start="09:00", end="17:00")
    headers = auth_headers(client, admin, la_org)

    # 17:00 UTC on that Monday is 10:00 in Los Angeles - inside the shift.
    inside = _pending(db, la_org, setup, MONDAY.replace(hour=17))
    assert _confirm(client, headers, inside, employee).status_code == 200

    # 09:00 UTC is 02:00 local - hours before it.
    outside = _pending(db, la_org, setup, MONDAY.replace(hour=9))
    refused = _confirm(client, headers, outside, employee)
    assert refused.status_code == 409
    assert "Outside working hours" in refused.json()["error"]["message"]
