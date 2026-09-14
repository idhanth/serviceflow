"""Roles are per-organization, map to permissions, and are enforced server-side."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.api.deps import ActiveUser, require_permission
from serviceflow.auth.permissions import Permission
from serviceflow.auth.principal import CurrentUser
from serviceflow.db.models.enums import MembershipStatus, Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.main import create_app
from tests.conftest import auth_headers, make_organization, make_user

# Module level, so FastAPI can resolve the string annotations below.
OwnerOnly = Annotated[CurrentUser, Depends(require_permission(Permission.ORGANIZATION_MANAGE))]
JobReaders = Annotated[
    CurrentUser, Depends(require_permission(Permission.JOBS_READ, Permission.JOBS_WORK))
]


@pytest.fixture()
def guarded_client() -> Iterator[TestClient]:
    """An app with probe routes, so guards are tested without waiting on features."""
    app: FastAPI = create_app()

    @app.get("/api/v1/_probe/settings")
    def _owner_only(user: OwnerOnly) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/_probe/jobs")
    def _job_readers(user: JobReaders) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/_probe/any")
    def _any(current_user: ActiveUser) -> dict[str, str]:
        return {"organization_id": str(current_user.organization_id)}

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("role", "settings_status", "jobs_status"),
    [
        (Role.OWNER, 200, 200),
        (Role.MANAGER, 403, 200),
        (Role.DISPATCHER, 403, 200),
        (Role.TECHNICIAN, 403, 200),
        (Role.ANALYST, 403, 200),
        (Role.CUSTOMER, 403, 403),
    ],
)
def test_permission_guards(
    guarded_client: TestClient,
    db: Session,
    organization: Organization,
    role: Role,
    settings_status: int,
    jobs_status: int,
) -> None:
    user = make_user(db, organization, role=role)
    headers = auth_headers(guarded_client, user)
    settings = guarded_client.get("/api/v1/_probe/settings", headers=headers)
    assert settings.status_code == settings_status
    if settings_status == 403:
        assert settings.json()["error"]["code"] == "INVALID_ROLE"
    assert guarded_client.get("/api/v1/_probe/jobs", headers=headers).status_code == jobs_status


def test_a_role_does_not_carry_across_organizations(
    guarded_client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.OWNER)
    second = make_organization(db, name="Harbor Plumbing")
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
    assert guarded_client.get("/api/v1/_probe/settings", headers=headers).status_code == 200

    as_customer = {**headers, "X-Organization-Id": str(second.id)}
    assert guarded_client.get("/api/v1/_probe/settings", headers=as_customer).status_code == 403


def test_suspended_membership_loses_access(
    guarded_client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(guarded_client, user)
    assert guarded_client.get("/api/v1/_probe/any", headers=headers).status_code == 200

    membership = db.query(OrganizationMembership).filter_by(user_id=user.id).one()
    membership.status = MembershipStatus.SUSPENDED
    db.commit()

    refused = guarded_client.get("/api/v1/_probe/any", headers=headers)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


def test_a_platform_admin_without_membership_cannot_read_tenant_routes(
    guarded_client: TestClient, db: Session, organization: Organization
) -> None:
    from serviceflow.auth.passwords import hash_password
    from serviceflow.db.models.user import User

    admin = User(
        auth_provider_id="dev|platform@example.com",
        email="platform@example.com",
        first_name="Platform",
        last_name="Admin",
        password_hash=hash_password("test-password-123"),
        is_platform_admin=True,
    )
    db.add(admin)
    db.commit()
    headers = auth_headers(guarded_client, admin)

    refused = guarded_client.get("/api/v1/_probe/any", headers=headers)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "TENANT_ACCESS_DENIED"
    assert guarded_client.get("/api/v1/platform/tenants", headers=headers).status_code == 200
