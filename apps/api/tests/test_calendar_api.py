"""Calendar feed: range handling, filters and role scoping (PRD 33)."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, JobStatus, Role
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_job,
    make_organization,
    make_service,
    make_user,
)

UTC = dt.UTC
DAY = dt.datetime(2027, 7, 5, 10, 0, tzinfo=UTC)  # a Monday


def _scheduled(
    db: Session,
    organization: Organization,
    setup: dict,
    employee,
    start,
    service=None,
    status=JobStatus.ASSIGNED,
):  # type: ignore[no-untyped-def]
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        service or setup["service"],
        start=start,
        status=BookingStatus.CONFIRMED,
    )
    booking.requested_end = start + dt.timedelta(hours=2)
    db.commit()
    job = make_job(db, organization, booking, employee, status=status)
    job.scheduled_start, job.scheduled_end = start, start + dt.timedelta(hours=2)
    db.commit()
    return job


def fetch(client: TestClient, headers: dict, start: dt.date, end: dt.date, **params):  # type: ignore[no-untyped-def]
    query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"/api/v1/calendar?start={start}&end={end}" + (f"&{query}" if query else "")
    return client.get(url, headers=headers)


def test_admin_sees_the_whole_shop_in_the_range(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    _scheduled(db, organization, setup, setup["employee"], DAY)
    _scheduled(db, organization, setup, colleague, DAY + dt.timedelta(hours=3))

    response = fetch(client, auth_headers(client, admin), DAY.date(), DAY.date())
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["timezone"] == organization.timezone
    assert body["can_filter_by_employee"] is True

    event = body["data"][0]
    assert event["customer_name"] and event["service_name"] and event["employee_name"]
    assert event["vehicle_name"] and event["status"] and event["duration_minutes"] == 120
    assert event["booking_id"]


def test_an_employee_sees_only_their_own_work(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    mine = _scheduled(db, organization, setup, setup["employee"], DAY)
    _scheduled(db, organization, setup, colleague, DAY + dt.timedelta(hours=3))

    body = fetch(
        client, auth_headers(client, setup["employee_user"]), DAY.date(), DAY.date()
    ).json()
    assert [e["id"] for e in body["data"]] == [str(mine.id)]
    assert body["can_filter_by_employee"] is False


def test_an_employee_filter_cannot_widen_an_employees_calendar(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    _scheduled(db, organization, setup, colleague, DAY)

    body = fetch(
        client,
        auth_headers(client, setup["employee_user"]),
        DAY.date(),
        DAY.date(),
        employee_id=colleague.id,
    ).json()
    assert body["data"] == []


def test_filters_by_employee_service_and_status(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    wash = make_service(db, organization, name="Express Wash", duration_minutes=45)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"], wash]
    )
    _scheduled(db, organization, setup, setup["employee"], DAY)
    _scheduled(db, organization, setup, colleague, DAY + dt.timedelta(hours=3), service=wash)
    _scheduled(
        db,
        organization,
        setup,
        colleague,
        DAY + dt.timedelta(hours=6),
        status=JobStatus.COMPLETED,
    )
    headers = auth_headers(client, admin)

    assert len(fetch(client, headers, DAY.date(), DAY.date()).json()["data"]) == 3
    assert (
        len(fetch(client, headers, DAY.date(), DAY.date(), employee_id=colleague.id).json()["data"])
        == 2
    )
    assert (
        len(fetch(client, headers, DAY.date(), DAY.date(), service_id=wash.id).json()["data"]) == 1
    )
    assert (
        len(fetch(client, headers, DAY.date(), DAY.date(), status="COMPLETED").json()["data"]) == 1
    )


def test_a_job_starting_before_the_window_but_running_into_it_is_included(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Overlap, not containment - otherwise a long job vanishes from day two."""
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    late = DAY.replace(hour=23)
    _scheduled(db, organization, setup, setup["employee"], late)  # 23:00 -> 01:00 next day

    tomorrow = (DAY + dt.timedelta(days=1)).date()
    body = fetch(client, auth_headers(client, admin), tomorrow, tomorrow).json()
    assert len(body["data"]) == 1


def test_events_are_ordered_by_start_time(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    for offset in (6, 0, 3):
        _scheduled(db, organization, setup, setup["employee"], DAY + dt.timedelta(hours=offset))

    starts = [
        e["scheduled_start"]
        for e in fetch(client, auth_headers(client, admin), DAY.date(), DAY.date()).json()["data"]
    ]
    assert starts == sorted(starts)


def test_a_backwards_or_oversized_range_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    backwards = fetch(client, headers, DAY.date(), DAY.date() - dt.timedelta(days=1))
    assert backwards.status_code == 422

    huge = fetch(client, headers, DAY.date(), DAY.date() + dt.timedelta(days=400))
    assert huge.status_code == 422


def test_customers_cannot_read_the_calendar(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = fetch(client, auth_headers(client, setup["customer_user"]), DAY.date(), DAY.date())
    assert response.status_code == 403


def test_the_calendar_is_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    rival = make_organization(db, name="Rival Detailing")
    rival_setup = booking_setup(db, rival)
    _scheduled(db, rival, rival_setup, rival_setup["employee"], DAY)

    body = fetch(client, auth_headers(client, admin), DAY.date(), DAY.date()).json()
    assert body["data"] == []


def test_the_range_is_interpreted_in_the_organization_timezone(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A job at 02:00 UTC belongs to the previous local day in Los Angeles."""
    la_org = make_organization(db, name="Pacific Detailing")
    la_org.timezone = "America/Los_Angeles"
    db.commit()
    admin = make_user(db, la_org, role=Role.ADMIN, email="pacific@example.com")
    setup = booking_setup(db, la_org)

    early_utc = dt.datetime(2027, 7, 6, 2, 0, tzinfo=UTC)  # 19:00 on 5 July, local
    _scheduled(db, la_org, setup, setup["employee"], early_utc)
    headers = auth_headers(client, admin, la_org)

    on_the_5th = fetch(client, headers, dt.date(2027, 7, 5), dt.date(2027, 7, 5)).json()
    on_the_6th = fetch(client, headers, dt.date(2027, 7, 6), dt.date(2027, 7, 6)).json()

    assert len(on_the_5th["data"]) == 1, "should belong to the local day it happens on"
    assert on_the_6th["data"] == []
