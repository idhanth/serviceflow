"""Job lifecycle, scoping, and invalid transitions."""

from __future__ import annotations

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


def _confirmed_job(db: Session, organization: Organization, setup: dict) -> Job:
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    return make_job(db, organization, booking, setup["employee"])


def test_employee_walks_a_job_through_its_lifecycle(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    job = _confirmed_job(db, organization, setup)
    headers = auth_headers(client, setup["employee_user"])

    started = client.post(f"/api/v1/jobs/{job.id}/start", headers=headers)
    assert started.status_code == 200
    assert started.json()["data"]["status"] == "IN_PROGRESS"
    assert started.json()["data"]["started_at"] is not None

    completed = client.post(
        f"/api/v1/jobs/{job.id}/complete",
        headers=headers,
        json={"internal_notes": "Clay bar needed a second pass."},
    )
    assert completed.status_code == 200
    data = completed.json()["data"]
    assert data["status"] == "COMPLETED"
    assert data["completed_at"] is not None
    assert data["internal_notes"] == "Clay bar needed a second pass."


@pytest.mark.parametrize(
    ("initial", "action"),
    [
        (JobStatus.SCHEDULED, "complete"),
        (JobStatus.IN_PROGRESS, "start"),
        (JobStatus.COMPLETED, "start"),
        (JobStatus.COMPLETED, "complete"),
        (JobStatus.CANCELLED, "start"),
        (JobStatus.CANCELLED, "complete"),
    ],
)
def test_invalid_transitions_return_409(
    client: TestClient,
    db: Session,
    organization: Organization,
    initial: JobStatus,
    action: str,
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    job = make_job(db, organization, booking, setup["employee"], status=initial)

    response = client.post(
        f"/api/v1/jobs/{job.id}/{action}",
        headers=auth_headers(client, setup["employee_user"]),
        json={} if action == "complete" else None,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    db.expire_all()
    assert db.get(Job, job.id).status is initial


def test_a_completed_job_cannot_go_back_to_in_progress(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The explicit backwards-transition case from PRD 12."""
    setup = booking_setup(db, organization)
    job = _confirmed_job(db, organization, setup)
    headers = auth_headers(client, setup["employee_user"])

    client.post(f"/api/v1/jobs/{job.id}/start", headers=headers)
    client.post(f"/api/v1/jobs/{job.id}/complete", headers=headers, json={})

    response = client.post(f"/api/v1/jobs/{job.id}/start", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    db.expire_all()
    assert db.get(Job, job.id).status is JobStatus.COMPLETED


def test_an_in_progress_job_cannot_be_cancelled(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    job = _confirmed_job(db, organization, setup)
    client.post(
        f"/api/v1/jobs/{job.id}/start", headers=auth_headers(client, setup["employee_user"])
    )

    response = client.post(f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers(client, admin))
    assert response.status_code == 409


def test_employee_sees_only_their_own_jobs(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    mine = _confirmed_job(db, organization, setup)

    other_booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    theirs = make_job(db, organization, other_booking, colleague)
    headers = auth_headers(client, setup["employee_user"])

    listing = client.get("/api/v1/jobs", headers=headers).json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["id"] == str(mine.id)

    # A colleague's job reads as missing, not forbidden.
    assert client.get(f"/api/v1/jobs/{theirs.id}", headers=headers).status_code == 404
    assert client.post(f"/api/v1/jobs/{theirs.id}/start", headers=headers).status_code == 404


def test_an_employee_filter_cannot_widen_an_employees_view(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    other_booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, other_booking, colleague)

    response = client.get(
        f"/api/v1/jobs?employee_id={colleague.id}",
        headers=auth_headers(client, setup["employee_user"]),
    )
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 0


def test_admin_sees_every_job_and_can_filter_by_employee(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    _confirmed_job(db, organization, setup)
    other_booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, other_booking, colleague)
    headers = auth_headers(client, admin)

    assert client.get("/api/v1/jobs", headers=headers).json()["meta"]["total"] == 2
    scoped = client.get(f"/api/v1/jobs?employee_id={colleague.id}", headers=headers).json()
    assert scoped["meta"]["total"] == 1


def test_customers_cannot_reach_jobs_at_all(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    job = _confirmed_job(db, organization, setup)
    headers = auth_headers(client, setup["customer_user"])

    assert client.get("/api/v1/jobs", headers=headers).status_code == 403
    assert client.get(f"/api/v1/jobs/{job.id}", headers=headers).status_code == 403
    assert client.post(f"/api/v1/jobs/{job.id}/start", headers=headers).status_code == 403


def test_employees_cannot_cancel_or_reassign(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    job = _confirmed_job(db, organization, setup)
    headers = auth_headers(client, setup["employee_user"])

    assert client.post(f"/api/v1/jobs/{job.id}/cancel", headers=headers).status_code == 403
    assert (
        client.post(
            f"/api/v1/jobs/{job.id}/assign",
            headers=headers,
            json={"employee_id": str(setup["employee"].id)},
        ).status_code
        == 403
    )


def test_admin_reassigns_an_unstarted_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    job = _confirmed_job(db, organization, setup)

    response = client.post(
        f"/api/v1/jobs/{job.id}/assign",
        headers=auth_headers(client, admin),
        json={"employee_id": str(colleague.id)},
    )
    assert response.status_code == 200
    assert response.json()["data"]["employee"]["id"] == str(colleague.id)


def test_reassignment_respects_qualification_and_job_state(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import make_service

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    other = make_service(db, organization, name="Express Wash", duration_minutes=45)
    unqualified = make_employee(db, organization, email="wrong@example.com", services=[other])
    job = _confirmed_job(db, organization, setup)
    headers = auth_headers(client, admin)

    refused = client.post(
        f"/api/v1/jobs/{job.id}/assign", headers=headers, json={"employee_id": str(unqualified.id)}
    )
    assert refused.status_code == 422

    client.post(
        f"/api/v1/jobs/{job.id}/start", headers=auth_headers(client, setup["employee_user"])
    )
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    started = client.post(
        f"/api/v1/jobs/{job.id}/assign", headers=headers, json={"employee_id": str(colleague.id)}
    )
    assert started.status_code == 409


def test_the_customer_sees_job_progress_on_their_booking(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The last link of the PRD 62 loop: status reaches the customer."""
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    job = make_job(db, organization, booking, setup["employee"])
    customer_headers = auth_headers(client, setup["customer_user"])

    before = client.get(f"/api/v1/bookings/{booking.id}", headers=customer_headers).json()
    assert before["data"]["job"]["status"] == "SCHEDULED"
    assert before["data"]["job"]["employee_name"] == setup["employee"].user.full_name

    client.post(
        f"/api/v1/jobs/{job.id}/start", headers=auth_headers(client, setup["employee_user"])
    )
    during = client.get(f"/api/v1/bookings/{booking.id}", headers=customer_headers).json()
    assert during["data"]["job"]["status"] == "IN_PROGRESS"

    client.post(
        f"/api/v1/jobs/{job.id}/complete",
        headers=auth_headers(client, setup["employee_user"]),
        json={"internal_notes": "Internal only."},
    )
    response = client.get(f"/api/v1/bookings/{booking.id}", headers=customer_headers)
    after = response.json()
    assert after["data"]["job"]["status"] == "COMPLETED"
    assert after["data"]["job"]["completed_at"] is not None
    # Internal notes must not leak to the customer anywhere in the payload.
    assert "Internal only." not in response.text
    assert after["data"]["admin_notes"] is None
