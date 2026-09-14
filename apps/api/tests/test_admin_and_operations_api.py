"""Members, platform tenants, settings, the dashboard, the schedule and self-service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.auth.passwords import hash_password
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import AuditAction, BookingStatus, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User
from tests.conftest import (
    TEST_PASSWORD,
    auth_headers,
    booking_setup,
    future_start,
    make_booking,
    make_organization,
    make_user,
)

# --------------------------------------------------------------- members


def test_an_owner_adds_a_technician_who_can_then_be_scheduled(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    response = client.post(
        "/api/v1/members",
        headers=auth_headers(client, owner),
        json={
            "email": "maya.brooks@example.com",
            "first_name": "Maya",
            "last_name": "Brooks",
            "role": "TECHNICIAN",
            "job_title": "Licensed Electrician",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["role"] == "TECHNICIAN"
    employee = db.query(Employee).join(User).filter(User.email == "maya.brooks@example.com").one()
    assert employee.job_title == "Licensed Electrician"
    assert db.query(AuditLog).filter_by(action=AuditAction.USER_INVITED).count() == 1


def test_role_changes_are_audited_and_the_last_owner_is_protected(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    dispatcher = make_user(db, organization, role=Role.DISPATCHER)
    headers = auth_headers(client, owner)
    membership = db.query(OrganizationMembership).filter_by(user_id=dispatcher.id).one()

    promoted = client.patch(
        f"/api/v1/members/{membership.id}", headers=headers, json={"role": "MANAGER"}
    )
    assert promoted.status_code == 200
    assert promoted.json()["data"]["role"] == "MANAGER"
    assert db.query(AuditLog).filter_by(action=AuditAction.USER_ROLE_CHANGED).count() == 1

    own = db.query(OrganizationMembership).filter_by(user_id=owner.id).one()
    refused = client.patch(f"/api/v1/members/{own.id}", headers=headers, json={"role": "ANALYST"})
    assert refused.status_code == 422


def test_a_suspended_member_loses_access_immediately(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    dispatcher = make_user(db, organization, role=Role.DISPATCHER)
    their_headers = auth_headers(client, dispatcher)
    assert client.get("/api/v1/bookings", headers=their_headers).status_code == 200

    membership = db.query(OrganizationMembership).filter_by(user_id=dispatcher.id).one()
    suspended = client.patch(
        f"/api/v1/members/{membership.id}",
        headers=auth_headers(client, owner),
        json={"status": "SUSPENDED"},
    )
    assert suspended.status_code == 200
    assert client.get("/api/v1/bookings", headers=their_headers).status_code == 403


def test_members_of_another_business_cannot_be_changed(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    rival = make_organization(db, name="Harbor Plumbing")
    rival_member = make_user(db, rival, role=Role.DISPATCHER)
    membership = db.query(OrganizationMembership).filter_by(user_id=rival_member.id).one()
    response = client.patch(
        f"/api/v1/members/{membership.id}",
        headers=auth_headers(client, owner),
        json={"role": "OWNER"},
    )
    assert response.status_code == 404
    db.refresh(membership)
    assert membership.role is Role.DISPATCHER


# --------------------------------------------------------------- settings and platform


def test_only_an_owner_changes_business_settings(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    manager = make_user(db, organization, role=Role.MANAGER)
    body = {"name": "Northside Home Services LLC", "timezone": "America/Chicago"}

    assert (
        client.patch(
            "/api/v1/organizations/current", headers=auth_headers(client, manager), json=body
        ).status_code
        == 403
    )
    changed = client.patch(
        "/api/v1/organizations/current", headers=auth_headers(client, owner), json=body
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["timezone"] == "America/Chicago"
    assert (
        client.patch(
            "/api/v1/organizations/current",
            headers=auth_headers(client, owner),
            json={"timezone": "Mars/Olympus"},
        ).status_code
        == 422
    )


def test_a_platform_admin_sees_tenant_sizes_but_not_tenant_records(
    client: TestClient, db: Session, organization: Organization
) -> None:
    booking_setup(db, organization)
    admin = User(
        auth_provider_id="dev|platform@example.com",
        email="platform@example.com",
        first_name="Taylor",
        last_name="Brooks",
        password_hash=hash_password(TEST_PASSWORD),
        is_platform_admin=True,
    )
    db.add(admin)
    db.commit()
    headers = auth_headers(client, admin)

    tenants = client.get("/api/v1/platform/tenants", headers=headers)
    assert tenants.status_code == 200
    row = next(t for t in tenants.json()["data"] if t["id"] == str(organization.id))
    assert row["customers"] == 1 and row["employees"] == 1

    for path in ("/api/v1/customers", "/api/v1/bookings", "/api/v1/jobs", "/api/v1/dashboard"):
        assert client.get(path, headers=headers).status_code == 403

    created = client.post(
        "/api/v1/platform/tenants",
        headers=headers,
        json={
            "name": "BrightSpace Cleaning Co.",
            "slug": "brightspace-cleaning",
            "email": "hello@brightspace.example.com",
            "timezone": "America/Denver",
            "owner_email": "grace@brightspace.example.com",
            "owner_first_name": "Grace",
            "owner_last_name": "Holloway",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["members"] == 1


def test_a_business_owner_cannot_use_platform_administration(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    assert (
        client.get("/api/v1/platform/tenants", headers=auth_headers(client, owner)).status_code
        == 403
    )


# --------------------------------------------------------------- dashboard and schedule


def test_the_dashboard_counts_only_this_tenants_work(
    client: TestClient, db: Session, organization: Organization
) -> None:
    dispatcher = make_user(db, organization, role=Role.DISPATCHER)
    setup = booking_setup(db, organization)
    soon = datetime.now(UTC) + timedelta(hours=3)
    make_booking(
        db, organization, setup["customer"], setup["service"], start=soon
    )  # NEW, unassigned

    rival = make_organization(db, name="Harbor Plumbing")
    rival_setup = booking_setup(db, rival)
    make_booking(db, rival, rival_setup["customer"], rival_setup["service"], start=soon)

    body = client.get("/api/v1/dashboard", headers=auth_headers(client, dispatcher)).json()["data"]
    assert body["counts"]["unassigned_jobs"] == 1
    assert len(body["needs_attention"]) == 1
    assert body["needs_attention"][0]["employee_id"] is None
    assert body["counts"]["technicians_total"] == 1


def test_the_schedule_shows_hours_and_a_technician_only_their_own_lane(
    client: TestClient, db: Session, organization: Organization
) -> None:
    owner = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    other = booking_setup(db, organization)
    start = future_start(days=4, hour=15)
    make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=start,
        status=BookingStatus.CONFIRMED,
        employee=setup["employee"],
    )
    make_booking(
        db,
        organization,
        other["customer"],
        other["service"],
        start=start,
        status=BookingStatus.CONFIRMED,
        employee=other["employee"],
    )
    day = start.date().isoformat()

    team = client.get(f"/api/v1/schedule?start={day}", headers=auth_headers(client, owner)).json()
    assert team["can_view_team"] is True
    assert len(team["lanes"]) == 2 and len(team["entries"]) == 2
    assert team["lanes"][0]["days"][0]["windows"] == [{"start": "00:00", "end": "23:59"}]

    mine = client.get(
        f"/api/v1/schedule?start={day}", headers=auth_headers(client, setup["employee_user"])
    ).json()
    assert mine["can_view_team"] is False
    assert [lane["employee_id"] for lane in mine["lanes"]] == [str(setup["employee"].id)]
    assert {entry["employee_id"] for entry in mine["entries"]} == {str(setup["employee"].id)}


def test_booking_with_a_technician_confirms_and_explains_a_conflict(
    client: TestClient, db: Session, organization: Organization
) -> None:
    dispatcher = make_user(db, organization, role=Role.DISPATCHER)
    setup = booking_setup(db, organization)
    other = booking_setup(db, organization)
    headers = auth_headers(client, dispatcher)
    start = future_start(days=6, hour=14)

    candidates = client.get(
        "/api/v1/scheduling/candidates",
        params={"service_id": str(setup["service"].id), "start": start.isoformat()},
        headers=headers,
    ).json()["data"]
    assert [c["id"] for c in candidates if c["assignable"]] == [str(setup["employee"].id)]

    booked = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "customer_id": str(setup["customer"].id),
            "service_id": str(setup["service"].id),
            "employee_id": str(setup["employee"].id),
            "requested_start": start.isoformat(),
        },
    )
    assert booked.status_code == 201, booked.text
    assert booked.json()["data"]["status"] == "CONFIRMED"
    assert booked.json()["data"]["job"]["status"] == "SCHEDULED"

    # The same technician, overlapping, for a different customer and service.
    make_user_qualified = db.get(Employee, setup["employee"].id)
    assert make_user_qualified is not None
    clash = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "customer_id": str(other["customer"].id),
            "service_id": str(setup["service"].id),
            "employee_id": str(setup["employee"].id),
            "requested_start": (start + timedelta(minutes=60)).isoformat(),
        },
    )
    assert clash.status_code == 409
    error = clash.json()["error"]
    assert error["code"] == "BOOKING_CONFLICT"
    assert (
        "is already booked from" in error["message"]
        and "Choose another employee or time" in error["message"]
    )
    # Nothing half-written: the refused booking left no booking and no job behind.
    assert db.query(Job).filter(Job.employee_id == setup["employee"].id).count() == 1
    assert db.query(Job).filter(Job.status == JobStatus.NEW).count() == 0


def test_a_customer_edits_their_own_profile_only(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    changed = client.patch(
        "/api/v1/customers/me",
        headers=headers,
        json={"address": "2230 Central Street, Evanston, IL 60201"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["address"] == "2230 Central Street, Evanston, IL 60201"
    # Staff edits of a customer record stay staff-only.
    assert (
        client.patch(
            f"/api/v1/customers/{setup['customer'].id}", headers=headers, json={"notes": "vip"}
        ).status_code
        == 403
    )
