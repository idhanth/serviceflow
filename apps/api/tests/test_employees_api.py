"""Employee endpoints, qualification assignment and deactivation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    make_employee,
    make_organization,
    make_service,
    make_user,
)


def test_admin_adds_an_employee_with_qualifications(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    wash = make_service(db, organization, name="Express Wash")
    detail = make_service(db, organization, name="Full Detail")

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(client, admin),
        json={
            "email": "tech@example.com",
            "first_name": "Tess",
            "last_name": "Tech",
            "job_title": "Detailer",
            "service_ids": [str(wash.id), str(detail.id)],
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["job_title"] == "Detailer"
    assert {s["name"] for s in data["services"]} == {"Express Wash", "Full Detail"}


def test_a_service_from_another_organization_cannot_be_assigned(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    foreign_org = make_organization(db, name="Rival Detailing")
    foreign_service = make_service(db, foreign_org, name="Foreign Service")

    response = client.post(
        "/api/v1/employees",
        headers=auth_headers(client, admin),
        json={
            "email": "tech@example.com",
            "first_name": "Tess",
            "last_name": "Tech",
            "service_ids": [str(foreign_service.id)],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_employees_cannot_read_the_roster(
    client: TestClient, db: Session, organization: Organization
) -> None:
    colleague = make_employee(db, organization, email="colleague@example.com")
    mine = make_employee(db, organization, email="mine@example.com")
    user = db.get(type(mine.user), mine.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    assert client.get("/api/v1/employees", headers=headers).status_code == 403
    assert client.get(f"/api/v1/employees/{colleague.id}", headers=headers).status_code == 403


def test_employee_reads_own_profile_via_me(
    client: TestClient, db: Session, organization: Organization
) -> None:
    service = make_service(db, organization, name="Interior Detail")
    mine = make_employee(db, organization, job_title="Interior Specialist", services=[service])
    user = db.get(type(mine.user), mine.user_id)
    assert user is not None

    response = client.get("/api/v1/employees/me", headers=auth_headers(client, user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(mine.id)
    assert data["job_title"] == "Interior Specialist"
    assert [s["name"] for s in data["services"]] == ["Interior Detail"]


def test_employees_cannot_promote_themselves(
    client: TestClient, db: Session, organization: Organization
) -> None:
    mine = make_employee(db, organization)
    user = db.get(type(mine.user), mine.user_id)
    assert user is not None

    response = client.patch(
        f"/api/v1/employees/{mine.id}",
        headers=auth_headers(client, user),
        json={"job_title": "Owner"},
    )
    assert response.status_code == 403


def test_deactivating_an_employee_revokes_their_access(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """PRD 53: a deactivated employee must lose access, not merely be hidden."""
    admin = make_user(db, organization, role=Role.ADMIN)
    employee = make_employee(db, organization)
    user = db.get(type(employee.user), employee.user_id)
    assert user is not None

    employee_headers = auth_headers(client, user)
    assert client.get("/api/v1/employees/me", headers=employee_headers).status_code == 200

    response = client.patch(
        f"/api/v1/employees/{employee.id}",
        headers=auth_headers(client, admin),
        json={"active": False},
    )
    assert response.status_code == 200
    assert response.json()["data"]["active"] is False

    membership = (
        db.query(OrganizationMembership).filter_by(user_id=user.id, role=Role.EMPLOYEE).one()
    )
    db.refresh(membership)
    assert membership.status is MembershipStatus.SUSPENDED
    assert client.get("/api/v1/employees/me", headers=employee_headers).status_code == 403


def test_reactivating_restores_access(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    employee = make_employee(db, organization, active=False)
    user = db.get(type(employee.user), employee.user_id)
    assert user is not None

    membership = (
        db.query(OrganizationMembership).filter_by(user_id=user.id, role=Role.EMPLOYEE).one()
    )
    membership.status = MembershipStatus.SUSPENDED
    db.commit()

    client.patch(
        f"/api/v1/employees/{employee.id}",
        headers=auth_headers(client, admin),
        json={"active": True},
    )
    db.refresh(membership)
    assert membership.status is MembershipStatus.ACTIVE


def test_filter_employees_by_service_and_active_state(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    coating = make_service(db, organization, name="Ceramic Coating")
    make_employee(db, organization, email="specialist@example.com", services=[coating])
    make_employee(db, organization, email="generalist@example.com", services=[])
    make_employee(db, organization, email="former@example.com", active=False)
    headers = auth_headers(client, admin)

    by_service = client.get(f"/api/v1/employees?service_id={coating.id}", headers=headers).json()
    assert by_service["meta"]["total"] == 1

    active_only = client.get("/api/v1/employees?active=true", headers=headers).json()
    assert active_only["meta"]["total"] == 2
