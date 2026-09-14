"""The audit trail: what it records, who may read it, and that it cannot change."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from serviceflow.core.errors import DependencyUnavailable
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.enums import AuditAction, Role
from serviceflow.db.models.organization import Organization
from serviceflow.services import audit
from serviceflow.services.scheduling import (
    AssignmentRequest,
    get_scheduling_policy,
    set_scheduling_policy,
)
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_booking,
    make_employee,
    make_organization,
    make_service,
    make_user,
)


def actions(db: Session) -> list[str]:
    return [
        row.action.value
        for row in db.query(AuditLog).order_by(AuditLog.created_at, AuditLog.id).all()
    ]


def entry(db: Session, action: AuditAction) -> AuditLog:
    return db.query(AuditLog).filter_by(action=action).one()


# ------------------------------------------------------------------ coverage


def test_booking_lifecycle_is_recorded(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, admin)

    created = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    ).json()["data"]

    client.post(
        f"/api/v1/bookings/{created['id']}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )
    client.post(
        f"/api/v1/bookings/{created['id']}/reschedule",
        headers=headers,
        json={"requested_start": future_start(days=9).isoformat()},
    )
    cancelled = client.post(f"/api/v1/bookings/{created['id']}/cancel", headers=headers, json={})
    assert cancelled.status_code == 200, cancelled.text

    recorded = actions(db)
    for expected in (
        "BOOKING_CREATED",
        "BOOKING_CONFIRMED",
        "JOB_ASSIGNED",
        "BOOKING_RESCHEDULED",
        "BOOKING_CANCELLED",
    ):
        assert expected in recorded, recorded


def test_a_jobs_whole_life_is_reachable_by_its_own_id(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Assignment is a JOB_* event, so it must be filed against the job.

    Filed against the booking instead, an admin filtering the feed by a job id
    would see it start and finish but never see who assigned it.
    """
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    setup = booking_setup(db, organization)

    created = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    ).json()["data"]
    confirmed = client.post(
        f"/api/v1/bookings/{created['id']}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    ).json()["data"]
    job_id = confirmed["job"]["id"]

    employee_headers = auth_headers(client, setup["employee_user"])
    client.post(f"/api/v1/jobs/{job_id}/start", headers=employee_headers)
    client.post(f"/api/v1/jobs/{job_id}/complete", headers=employee_headers, json={})

    feed = client.get(
        f"/api/v1/activity?resource_id={job_id}&sort=created_at", headers=headers
    ).json()["data"]
    assert [entry["action"] for entry in feed] == [
        "JOB_ASSIGNED",
        "JOB_STARTED",
        "JOB_COMPLETED",
    ]
    assert {entry["resource_type"] for entry in feed} == {"job"}


def test_customer_records_are_audited_without_copying_personal_data(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)

    created = client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "email": "audited.customer@example.com",
            "first_name": "Audited",
            "last_name": "Customer",
            "phone": "+1 555 0100",
        },
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["data"]["id"]

    updated = client.patch(
        f"/api/v1/customers/{customer_id}", headers=headers, json={"phone": "+1 555 0199"}
    )
    assert updated.status_code == 200, updated.text

    entries = db.query(AuditLog).order_by(AuditLog.created_at).all()
    assert [e.action.value for e in entries] == ["CUSTOMER_CREATED", "CUSTOMER_UPDATED"]
    assert all(e.actor_user_id == admin.id for e in entries)

    # The trail says what changed, not what it changed to.
    written = str([e.metadata_ for e in entries])
    assert "phone" in written
    for value in ("555 0100", "555 0199", "audited.customer@example.com"):
        assert value not in written, value


def test_rejection_is_recorded(client: TestClient, db: Session, organization: Organization) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=4),
    )
    client.post(
        f"/api/v1/bookings/{booking.id}/reject", headers=auth_headers(client, admin), json={}
    )
    assert "BOOKING_REJECTED" in actions(db)


def test_job_lifecycle_is_recorded(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])

    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(f"/api/v1/jobs/{parties['job'].id}/complete", headers=staff, json={})

    recorded = actions(db)
    assert "JOB_STARTED" in recorded
    assert "JOB_COMPLETED" in recorded


def test_reassignment_records_both_technicians(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    parties = job_with_parties(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[parties["service"]]
    )

    client.post(
        f"/api/v1/jobs/{parties['job'].id}/assign",
        headers=auth_headers(client, admin),
        json={"employee_id": str(colleague.id)},
    )

    row = entry(db, AuditAction.JOB_REASSIGNED)
    assert row.metadata_["from"] == parties["employee"].user.full_name
    assert row.metadata_["to"] == colleague.user.full_name


def test_employee_and_service_changes_are_recorded(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)

    created = client.post(
        "/api/v1/employees",
        headers=headers,
        json={"email": "new@example.com", "first_name": "New", "last_name": "Hire"},
    ).json()["data"]
    client.patch(f"/api/v1/employees/{created['id']}", headers=headers, json={"active": False})

    service = client.post(
        "/api/v1/services",
        headers=headers,
        json={"name": "Ceramic Coating", "base_price": "900.00", "duration_minutes": 480},
    ).json()["data"]
    client.delete(f"/api/v1/services/{service['id']}", headers=headers)

    recorded = actions(db)
    assert "EMPLOYEE_CREATED" in recorded
    assert "EMPLOYEE_DEACTIVATED" in recorded
    assert "SERVICE_CREATED" in recorded
    assert "SERVICE_RETIRED" in recorded


def test_availability_changes_are_recorded(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    employee = make_employee(db, organization, email="tech@example.com")
    headers = auth_headers(client, admin)
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()

    client.put(
        f"/api/v1/employees/{employee.id}/availability",
        headers=headers,
        json={"windows": [{"day_of_week": 0, "start_time": "09:00", "end_time": "17:00"}]},
    )
    override = client.post(
        f"/api/v1/employees/{employee.id}/availability/overrides",
        headers=headers,
        json={"date": tomorrow, "available": False, "reason": "Training"},
    ).json()["data"]
    client.delete(
        f"/api/v1/employees/{employee.id}/availability/overrides/{override['id']}",
        headers=headers,
    )

    recorded = actions(db)
    assert "AVAILABILITY_UPDATED" in recorded
    assert "AVAILABILITY_OVERRIDE_SET" in recorded
    assert "AVAILABILITY_OVERRIDE_REMOVED" in recorded


def test_note_and_photo_removal_are_recorded_without_their_content(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])

    note = client.post(
        f"/api/v1/jobs/{parties['job'].id}/notes",
        headers=staff,
        json={"content": "SECRET-INTERNAL never record this", "visibility": "INTERNAL"},
    ).json()["data"]
    client.delete(f"/api/v1/jobs/{parties['job'].id}/notes/{note['id']}", headers=staff)

    recorded = actions(db)
    assert "NOTE_ADDED" in recorded
    assert "NOTE_DELETED" in recorded
    # The trail says a note happened, never what it said.
    for row in db.query(AuditLog).all():
        assert "SECRET-INTERNAL" not in str(row.metadata_)


# ------------------------------------------------------------------ correctness


def test_the_actor_and_organization_come_from_the_session(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Never from the request body - a client cannot attribute an action."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=4),
    )

    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={
            "employee_id": str(setup["employee"].id),
            # A hopeful client trying to attribute this elsewhere.
            "actor_user_id": str(setup["customer_user"].id),
            "organization_id": str(make_organization(db, name="Elsewhere").id),
        },
    )

    row = entry(db, AuditAction.BOOKING_CONFIRMED)
    assert row.actor_user_id == admin.id
    assert row.organization_id == organization.id


def test_metadata_drops_credential_shaped_values() -> None:
    cleaned = audit._safe_metadata(
        {
            "service": "Full Detail",
            "password": "hunter2",
            "auth_token": "abc",
            "x-amz-signature": "sig",
            "api_key": "k",
            "long": "x" * 500,
        }
    )
    assert cleaned is not None
    assert cleaned["service"] == "Full Detail"
    for dropped in ("password", "auth_token", "x-amz-signature", "api_key"):
        assert dropped not in cleaned
    assert len(cleaned["long"]) <= 201


def test_a_rolled_back_action_leaves_no_audit_row(
    client: TestClient, db: Session, organization: Organization
) -> None:
    class ExplodingPolicy:
        def check_assignment(self, session, request: AssignmentRequest) -> None:  # type: ignore[no-untyped-def]
            raise DependencyUnavailable("Scheduling is unavailable.")

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=4),
    )

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
    db.expire_all()
    assert db.query(AuditLog).filter_by(action=AuditAction.BOOKING_CONFIRMED).count() == 0


# ------------------------------------------------------------------ immutability


def test_an_audit_row_cannot_be_updated_or_deleted(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Enforced by a database trigger, not by convention."""
    parties = job_with_parties(db, organization)
    client.post(
        f"/api/v1/jobs/{parties['job'].id}/start",
        headers=auth_headers(client, parties["employee_user"]),
    )
    row = entry(db, AuditAction.JOB_STARTED)

    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE audit_logs SET action = 'JOB_COMPLETED' WHERE id = :id"),
            {"id": row.id},
        )
    db.rollback()

    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": row.id})
    db.rollback()

    db.expire_all()
    assert db.query(AuditLog).filter_by(id=row.id).count() == 1


def test_no_route_writes_to_the_activity_feed(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    payload = {"action": "BOOKING_CREATED", "resource_type": "booking"}

    for method in ("post", "patch", "put", "delete"):
        response = getattr(client, method)(
            "/api/v1/activity", headers=headers, **({"json": payload} if method != "delete" else {})
        )
        assert response.status_code == 405, method


# ------------------------------------------------------------------ the feed


def test_only_admins_read_the_activity_feed(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    for user in (parties["customer_user"], parties["employee_user"]):
        assert client.get("/api/v1/activity", headers=auth_headers(client, user)).status_code == 403


def test_the_feed_is_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    rival = make_organization(db, name="Rival Detailing")
    rival_parties = job_with_parties(db, rival)
    client.post(
        f"/api/v1/jobs/{rival_parties['job'].id}/start",
        headers=auth_headers(client, rival_parties["employee_user"], rival),
    )
    assert db.query(AuditLog).count() == 1

    feed = client.get("/api/v1/activity", headers=auth_headers(client, admin)).json()
    assert feed["meta"]["total"] == 0


def test_the_feed_filters_sorts_and_paginates(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    for index in range(4):
        make_service(db, organization, name=f"Service {index}")
        client.post(
            "/api/v1/services",
            headers=headers,
            json={
                "name": f"Audited {index}",
                "base_price": "10.00",
                "duration_minutes": 30,
            },
        )
    parties = job_with_parties(db, organization)
    client.post(
        f"/api/v1/jobs/{parties['job'].id}/start",
        headers=auth_headers(client, parties["employee_user"]),
    )

    everything = client.get("/api/v1/activity?page_size=50", headers=headers).json()
    assert everything["meta"]["total"] >= 5

    by_action = client.get("/api/v1/activity?action=SERVICE_CREATED", headers=headers).json()
    assert by_action["meta"]["total"] == 4
    assert all(row["action"] == "SERVICE_CREATED" for row in by_action["data"])

    by_actor = client.get(
        f"/api/v1/activity?actor_user_id={admin.id}&page_size=50", headers=headers
    ).json()
    assert all(row["actor_name"] == admin.full_name for row in by_actor["data"])

    by_resource = client.get("/api/v1/activity?resource_type=job", headers=headers).json()
    assert all(row["resource_type"] == "job" for row in by_resource["data"])

    page = client.get("/api/v1/activity?page=1&page_size=2", headers=headers).json()
    assert len(page["data"]) == 2
    newest_first = [row["created_at"] for row in everything["data"]]
    assert newest_first == sorted(newest_first, reverse=True)

    oldest_first = client.get(
        "/api/v1/activity?sort=created_at&page_size=50", headers=headers
    ).json()["data"]
    stamps = [row["created_at"] for row in oldest_first]
    assert stamps == sorted(stamps)


def test_the_actor_filter_list_is_scoped(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    parties = job_with_parties(db, organization)
    client.post(
        f"/api/v1/jobs/{parties['job'].id}/start",
        headers=auth_headers(client, parties["employee_user"]),
    )

    actors = client.get("/api/v1/activity/actors", headers=auth_headers(client, admin)).json()
    names = {row["full_name"] for row in actors["data"]}
    assert parties["employee"].user.full_name in names
