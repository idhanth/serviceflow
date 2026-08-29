"""PRD 6: roles are per-organization and enforced server-side."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.api.deps import ActiveUser, AdminUser, EmployeeUser
from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.main import create_app
from tests.conftest import auth_headers, make_user


@pytest.fixture()
def guarded_client() -> TestClient:
    """An app with probe routes, so guards are tested without waiting on features."""
    app: FastAPI = create_app()

    @app.get("/api/v1/_probe/admin")
    def _admin_only(user: AdminUser) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/_probe/staff")
    def _staff_only(user: EmployeeUser) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/_probe/any")
    def _any(current_user: ActiveUser) -> dict[str, str]:
        return {"organization_id": str(current_user.organization_id)}

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("role", "admin_status", "staff_status"),
    [
        (Role.ADMIN, 200, 200),
        (Role.EMPLOYEE, 403, 200),
        (Role.CUSTOMER, 403, 403),
    ],
)
def test_role_guards(
    guarded_client: TestClient,
    db: Session,
    organization: Organization,
    role: Role,
    admin_status: int,
    staff_status: int,
) -> None:
    user = make_user(db, organization, role=role)
    headers = auth_headers(guarded_client, user)
    assert guarded_client.get("/api/v1/_probe/admin", headers=headers).status_code == admin_status
    assert guarded_client.get("/api/v1/_probe/staff", headers=headers).status_code == staff_status


def test_a_role_does_not_carry_across_organizations(
    guarded_client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import make_organization

    user = make_user(db, organization, role=Role.ADMIN)
    second = make_organization(db, name="Second Shop")
    db.add(
        OrganizationMembership(
            organization_id=second.id,
            user_id=user.id,
            role=Role.CUSTOMER,
            status=MembershipStatus.ACTIVE,
        )
    )
    db.commit()

    headers = auth_headers(guarded_client, user, organization)
    assert guarded_client.get("/api/v1/_probe/admin", headers=headers).status_code == 200

    as_customer = {**headers, "X-Organization-Id": str(second.id)}
    assert guarded_client.get("/api/v1/_probe/admin", headers=as_customer).status_code == 403


def test_suspended_membership_loses_access(
    guarded_client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(guarded_client, user)
    assert guarded_client.get("/api/v1/_probe/any", headers=headers).status_code == 200

    membership = db.query(OrganizationMembership).filter_by(user_id=user.id).one()
    membership.status = MembershipStatus.SUSPENDED
    db.commit()

    assert guarded_client.get("/api/v1/_probe/any", headers=headers).status_code == 403
