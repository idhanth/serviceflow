"""Cross-organization access attempts against bookings and jobs (PRD 5)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    make_booking,
    make_job,
    make_organization,
    make_user,
)


@pytest.fixture()
def rival(db: Session) -> dict:
    """A second organization with its own booking and job."""
    org = make_organization(db, name="Rival Detailing")
    setup = booking_setup(db, org)
    booking = make_booking(
        db,
        org,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    job = make_job(db, org, booking, setup["employee"])
    return {"organization": org, "booking": booking, "job": job, "setup": setup}


def test_a_foreign_booking_is_not_readable_or_mutable(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    booking_id = rival["booking"].id

    assert client.get(f"/api/v1/bookings/{booking_id}", headers=headers).status_code == 404
    assert (
        client.post(
            f"/api/v1/bookings/{booking_id}/confirm",
            headers=headers,
            json={"employee_id": str(rival["setup"]["employee"].id)},
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/bookings/{booking_id}/reject", headers=headers, json={}).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers, json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/bookings/{booking_id}/reschedule",
            headers=headers,
            json={"requested_start": future_start().isoformat()},
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/bookings/{booking_id}", headers=headers, json={"admin_notes": "pwned"}
        ).status_code
        == 404
    )

    db.expire_all()
    assert db.get(Booking, booking_id).status is BookingStatus.CONFIRMED
    assert db.get(Booking, booking_id).admin_notes is None


def test_a_foreign_job_is_not_readable_or_mutable(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    job_id = rival["job"].id

    assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).status_code == 404
    assert client.post(f"/api/v1/jobs/{job_id}/start", headers=headers).status_code == 404
    assert (
        client.post(f"/api/v1/jobs/{job_id}/complete", headers=headers, json={}).status_code == 404
    )
    assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers).status_code == 404

    db.expire_all()
    stored = db.get(Job, job_id)
    assert stored.status.value == "ASSIGNED"
    assert stored.started_at is None


def test_foreign_ids_are_indistinguishable_from_nonexistent_ones(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    missing = uuid.uuid4()

    for template, foreign_id in [
        ("/api/v1/bookings/{}", rival["booking"].id),
        ("/api/v1/jobs/{}", rival["job"].id),
    ]:
        foreign = client.get(template.format(foreign_id), headers=headers)
        absent = client.get(template.format(missing), headers=headers)
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json()["error"]["code"] == absent.json()["error"]["code"]
        assert foreign.json()["error"]["message"] == absent.json()["error"]["message"]


def test_listings_never_include_another_organizations_rows(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    make_booking(db, organization, setup["customer"], setup["vehicle"], setup["service"])
    headers = auth_headers(client, admin)

    bookings = client.get("/api/v1/bookings?page_size=100", headers=headers).json()
    assert bookings["meta"]["total"] == 1
    assert str(rival["booking"].id) not in {row["id"] for row in bookings["data"]}

    jobs = client.get("/api/v1/jobs?page_size=100", headers=headers).json()
    assert jobs["meta"]["total"] == 0


def test_a_foreign_employee_cannot_be_assigned_to_a_local_booking(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["vehicle"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(rival["setup"]["employee"].id)},
    )
    assert response.status_code == 404

    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING
    assert db.query(Job).filter_by(organization_id=organization.id).count() == 0


def test_a_foreign_vehicle_or_service_cannot_be_booked_locally(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    foreign_vehicle = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "vehicle_id": str(rival["setup"]["vehicle"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    foreign_service = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "vehicle_id": str(setup["vehicle"].id),
            "service_id": str(rival["setup"]["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert foreign_vehicle.status_code == 404
    assert foreign_service.status_code == 404
    assert db.query(Booking).filter_by(organization_id=organization.id).count() == 0


def test_the_rivals_own_admin_cannot_reach_our_records(
    client: TestClient, db: Session, organization: Organization, rival: dict
) -> None:
    """Isolation is mutual, not just one-directional."""
    rival_admin = make_user(
        db, rival["organization"], role=Role.ADMIN, email="rival-admin@example.com"
    )
    setup = booking_setup(db, organization)
    ours = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    our_job = make_job(db, organization, ours, setup["employee"])
    headers = auth_headers(client, rival_admin)

    assert client.get(f"/api/v1/bookings/{ours.id}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/jobs/{our_job.id}", headers=headers).status_code == 404
