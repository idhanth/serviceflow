"""Confirmation: assignment rules, and the transactional job-creation guarantees."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.core.errors import DependencyUnavailable
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from serviceflow.services.scheduling import (
    AssignmentRequest,
    QualificationPolicy,
    get_scheduling_policy,
    set_scheduling_policy,
)
from tests.conftest import (
    auth_headers,
    booking_setup,
    make_booking,
    make_employee,
    make_service,
    make_user,
)


def test_confirmation_creates_exactly_one_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id), "admin_notes": "Assigned to Erin."},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CONFIRMED"
    assert data["job"]["status"] == "SCHEDULED"
    assert data["job"]["employee_name"] == setup["employee"].user.full_name

    jobs = db.query(Job).filter_by(booking_id=booking.id).all()
    assert len(jobs) == 1
    # The job inherits the booking's window rather than inventing its own.
    assert jobs[0].scheduled_start == booking.requested_start
    assert jobs[0].scheduled_end == booking.requested_end


def test_confirming_twice_does_not_create_a_second_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, admin)
    payload = {"employee_id": str(setup["employee"].id)}

    first = client.post(f"/api/v1/bookings/{booking.id}/confirm", headers=headers, json=payload)
    second = client.post(f"/api/v1/bookings/{booking.id}/confirm", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert db.query(Job).filter_by(booking_id=booking.id).count() == 1


def test_a_second_job_row_is_refused_by_the_database(
    db: Session, organization: Organization
) -> None:
    """Belt and braces: even bypassing the service layer cannot duplicate a job."""
    from sqlalchemy.exc import IntegrityError

    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    # make_booking already wrote the booking's one job; a second must be refused.
    db.add(
        Job(
            organization_id=organization.id,
            booking_id=booking.id,
            employee_id=setup["employee"].id,
            scheduled_start=booking.requested_start,
            scheduled_end=booking.requested_end,
            status=JobStatus.SCHEDULED,
        )
    )
    with pytest.raises(IntegrityError, match="one_job_per_booking"):
        db.commit()
    db.rollback()


def test_an_inactive_employee_cannot_be_assigned(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    setup["employee"].active = False
    db.commit()
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["employee_id"]

    # The booking must be untouched and no job created.
    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING
    assert (
        db.query(Job).filter(Job.employee_id.is_not(None)).count() == 0
    )  # the booking's job stays unassigned


def test_an_unqualified_employee_cannot_be_assigned(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    other_service = make_service(db, organization, name="Express Wash", duration_minutes=45)
    generalist = make_employee(
        db, organization, email="generalist@example.com", services=[other_service]
    )
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(generalist.id)},
    )
    assert response.status_code == 422
    assert "qualified" in response.json()["error"]["message"]

    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING
    assert (
        db.query(Job).filter(Job.employee_id.is_not(None)).count() == 0
    )  # the booking's job stays unassigned


def test_confirmation_rolls_back_when_job_creation_fails(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A confirmed booking must never exist without its job.

    A policy that raises after the booking has been transitioned stands in for any
    mid-transaction failure; the booking has to come back PENDING.
    """

    class ExplodingPolicy:
        def check_assignment(self, session, request: AssignmentRequest) -> None:  # type: ignore[no-untyped-def]
            raise DependencyUnavailable("Scheduling service is unavailable.")

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    previous = get_scheduling_policy()
    set_scheduling_policy(ExplodingPolicy())
    try:
        response = client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=auth_headers(client, admin),
            json={"employee_id": str(setup["employee"].id)},
        )
    finally:
        set_scheduling_policy(previous)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"

    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING
    assert (
        db.query(Job).filter(Job.employee_id.is_not(None)).count() == 0
    )  # the booking's job stays unassigned

    # And the booking is still confirmable once the dependency recovers.
    recovery = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )
    assert recovery.status_code == 200
    assert db.query(Job).count() == 1


def test_the_scheduling_policy_seam_is_actually_consulted(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Phase 4 plugs its engine in here, so confirmation must call it."""
    calls: list[AssignmentRequest] = []

    class RecordingPolicy(QualificationPolicy):
        def check_assignment(self, session, request: AssignmentRequest) -> None:  # type: ignore[no-untyped-def]
            calls.append(request)
            super().check_assignment(session, request)

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    previous = get_scheduling_policy()
    set_scheduling_policy(RecordingPolicy())
    try:
        client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=auth_headers(client, admin),
            json={"employee_id": str(setup["employee"].id)},
        )
    finally:
        set_scheduling_policy(previous)

    assert len(calls) == 1
    assert calls[0].employee.id == setup["employee"].id
    assert calls[0].start == booking.requested_start
    assert calls[0].end == booking.requested_end


def test_assignable_employees_lists_only_active_qualified_staff(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    other = make_service(db, organization, name="Express Wash", duration_minutes=45)
    make_employee(db, organization, email="unqualified@example.com", services=[other])
    make_employee(
        db, organization, email="retired@example.com", services=[setup["service"]], active=False
    )
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    response = client.get(
        f"/api/v1/bookings/{booking.id}/assignable-employees",
        headers=auth_headers(client, admin),
    )
    assert response.status_code == 200
    candidates = response.json()["data"]
    assert [candidate["id"] for candidate in candidates] == [str(setup["employee"].id)]


def test_rejecting_a_booking_creates_no_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/reject",
        headers=auth_headers(client, admin),
        json={"admin_notes": "Fully booked that day."},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "REJECTED"
    assert response.json()["data"]["admin_notes"] == "Fully booked that day."
    assert db.query(Job).filter(Job.status != JobStatus.CANCELLED).count() == 0  # cancelled with it


def test_rescheduling_moves_the_job_window_too(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import future_start

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, admin)
    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )

    new_start = future_start(days=9, hour=14)
    response = client.post(
        f"/api/v1/bookings/{booking.id}/reschedule",
        headers=headers,
        json={"requested_start": new_start.isoformat()},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requested_start"] == data["job"]["scheduled_start"]
    assert data["requested_end"] == data["job"]["scheduled_end"]

    # Compare instants, not strings: the same moment can be written "Z" or "+00:00".
    job = db.query(Job).filter_by(booking_id=booking.id).one()
    db.refresh(job)
    assert job.scheduled_start == datetime.fromisoformat(data["job"]["scheduled_start"])
    assert data["job"]["scheduled_start"].endswith("Z")


def test_a_started_job_blocks_reschedule_and_cancel(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import future_start

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, admin)
    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )
    job = db.query(Job).filter_by(booking_id=booking.id).one()
    client.post(
        f"/api/v1/jobs/{job.id}/start", headers=auth_headers(client, setup["employee_user"])
    )

    moved = client.post(
        f"/api/v1/bookings/{booking.id}/reschedule",
        headers=headers,
        json={"requested_start": future_start(days=12).isoformat()},
    )
    cancelled = client.post(f"/api/v1/bookings/{booking.id}/cancel", headers=headers, json={})

    assert moved.status_code == 409
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_cancelling_a_confirmed_booking_cancels_its_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, admin)
    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )

    response = client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers=headers,
        json={"reason": "Customer called."},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"

    job = db.query(Job).filter_by(booking_id=booking.id).one()
    db.refresh(job)
    assert job.status is JobStatus.CANCELLED
