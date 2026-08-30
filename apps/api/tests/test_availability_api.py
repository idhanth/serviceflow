"""Availability management endpoints and their access boundaries."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.availability import AvailabilityOverride, EmployeeAvailability
from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_employee,
    make_organization,
    make_user,
)

TOMORROW = dt.date.today() + dt.timedelta(days=1)


def weekly_payload(*windows: tuple[int, str, str]) -> dict:
    return {
        "windows": [
            {"day_of_week": day, "start_time": start, "end_time": end}
            for day, start, end in windows
        ]
    }


def test_employee_reads_and_replaces_their_own_schedule(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    employee = setup["employee"]
    headers = auth_headers(client, setup["employee_user"])

    response = client.put(
        f"/api/v1/employees/{employee.id}/availability",
        headers=headers,
        json=weekly_payload((0, "09:00", "17:00"), (1, "09:00", "17:00")),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert [w["day_of_week"] for w in data["weekly"]] == [0, 1]
    assert data["timezone"] == organization.timezone

    # Replacement is wholesale: the fixture's round-the-clock week is gone.
    assert db.query(EmployeeAvailability).filter_by(employee_id=employee.id).count() == 2


def test_a_split_shift_is_accepted(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.put(
        f"/api/v1/employees/{setup['employee'].id}/availability",
        headers=auth_headers(client, setup["employee_user"]),
        json=weekly_payload((2, "08:00", "12:00"), (2, "13:00", "18:00")),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["weekly"]) == 2


def test_overlapping_shifts_on_one_day_are_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.put(
        f"/api/v1/employees/{setup['employee'].id}/availability",
        headers=auth_headers(client, setup["employee_user"]),
        json=weekly_payload((0, "09:00", "13:00"), (0, "12:00", "17:00")),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_a_backwards_shift_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.put(
        f"/api/v1/employees/{setup['employee'].id}/availability",
        headers=auth_headers(client, setup["employee_user"]),
        json=weekly_payload((0, "17:00", "09:00")),
    )
    assert response.status_code == 422


def test_an_employee_cannot_touch_a_colleagues_schedule(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(db, organization, email="colleague@example.com")
    headers = auth_headers(client, setup["employee_user"])

    assert (
        client.get(f"/api/v1/employees/{colleague.id}/availability", headers=headers).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/employees/{colleague.id}/availability",
            headers=headers,
            json=weekly_payload((0, "09:00", "17:00")),
        ).status_code
        == 403
    )


def test_admin_manages_anyone_in_the_organization(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    employee = make_employee(db, organization, email="tech@example.com")

    response = client.put(
        f"/api/v1/employees/{employee.id}/availability",
        headers=auth_headers(client, admin),
        json=weekly_payload((4, "10:00", "16:00")),
    )
    assert response.status_code == 200
    assert response.json()["data"]["weekly"][0]["start_time"] == "10:00:00"


def test_customers_have_no_availability_access(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    assert (
        client.get(
            f"/api/v1/employees/{setup['employee'].id}/availability", headers=headers
        ).status_code
        == 403
    )


# ------------------------------------------------------------------ overrides


def test_creating_and_removing_an_unavailable_override(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["employee_user"])
    path = f"/api/v1/employees/{setup['employee'].id}/availability/overrides"

    created = client.post(
        path,
        headers=headers,
        json={"date": TOMORROW.isoformat(), "available": False, "reason": "Vacation"},
    )
    assert created.status_code == 201
    body = created.json()["data"]
    assert body["available"] is False
    assert body["reason"] == "Vacation"

    listed = client.get(
        f"/api/v1/employees/{setup['employee'].id}/availability", headers=headers
    ).json()["data"]
    assert len(listed["overrides"]) == 1

    removed = client.delete(f"{path}/{body['id']}", headers=headers)
    assert removed.status_code == 204
    assert db.query(AvailabilityOverride).count() == 0


def test_special_availability_requires_hours(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.post(
        f"/api/v1/employees/{setup['employee'].id}/availability/overrides",
        headers=auth_headers(client, setup["employee_user"]),
        json={"date": TOMORROW.isoformat(), "available": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["start_time"]


def test_setting_an_override_twice_replaces_it(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """One override per date keeps the precedence rules unambiguous."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["employee_user"])
    path = f"/api/v1/employees/{setup['employee'].id}/availability/overrides"

    client.post(path, headers=headers, json={"date": TOMORROW.isoformat(), "available": False})
    second = client.post(
        path,
        headers=headers,
        json={
            "date": TOMORROW.isoformat(),
            "available": True,
            "start_time": "18:00",
            "end_time": "21:00",
            "reason": "Evening cover",
        },
    )
    assert second.status_code == 201
    assert db.query(AvailabilityOverride).count() == 1
    assert second.json()["data"]["available"] is True


def test_past_overrides_are_hidden_unless_asked_for(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import set_override

    setup = booking_setup(db, organization)
    set_override(
        db, setup["employee"], date=dt.date.today() - dt.timedelta(days=5), available=False
    )
    headers = auth_headers(client, setup["employee_user"])
    base = f"/api/v1/employees/{setup['employee'].id}/availability"

    assert client.get(base, headers=headers).json()["data"]["overrides"] == []
    assert (
        len(client.get(f"{base}?include_past=true", headers=headers).json()["data"]["overrides"])
        == 1
    )


# ------------------------------------------------------------------ tenancy


def test_availability_is_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    rival = make_organization(db, name="Rival Detailing")
    rival_employee = make_employee(db, rival, email="rival-tech@example.com")
    headers = auth_headers(client, admin)
    path = f"/api/v1/employees/{rival_employee.id}/availability"

    assert client.get(path, headers=headers).status_code == 404
    assert (
        client.put(path, headers=headers, json=weekly_payload((0, "09:00", "17:00"))).status_code
        == 404
    )
    assert (
        client.post(
            f"{path}/overrides",
            headers=headers,
            json={"date": TOMORROW.isoformat(), "available": False},
        ).status_code
        == 404
    )
    # Nothing was written into the rival organization: the fixture's default
    # round-the-clock week (one row per day) is untouched, and no override exists.
    assert db.query(EmployeeAvailability).filter_by(employee_id=rival_employee.id).count() == 7
    assert db.query(AvailabilityOverride).filter_by(employee_id=rival_employee.id).count() == 0
