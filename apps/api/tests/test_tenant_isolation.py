"""PRD 5: a member of organization A must never reach organization B's data."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import auth_headers, make_organization, make_user


def test_request_is_scoped_to_the_callers_organization(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    response = client.get("/api/v1/organizations/current", headers=auth_headers(client, admin))
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(organization.id)


def test_foreign_organization_header_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    other_org = make_organization(db, name="Rival Detailing")
    make_user(db, other_org, role=Role.ADMIN)

    headers = auth_headers(client, admin)
    headers["X-Organization-Id"] = str(other_org.id)
    response = client.get("/api/v1/organizations/current", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_unknown_and_foreign_organizations_are_indistinguishable(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A 404 for one and a 403 for the other would leak which organizations exist."""
    admin = make_user(db, organization, role=Role.ADMIN)
    other_org = make_organization(db, name="Rival Detailing")

    foreign = client.get(
        "/api/v1/organizations/current",
        headers={**auth_headers(client, admin), "X-Organization-Id": str(other_org.id)},
    )
    nonexistent = client.get(
        "/api/v1/organizations/current",
        headers={
            **auth_headers(client, admin),
            "X-Organization-Id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert foreign.status_code == nonexistent.status_code == 403
    assert foreign.json()["error"] == nonexistent.json()["error"] | {
        "request_id": foreign.json()["error"]["request_id"]
    }


def test_malformed_organization_header_is_refused_not_crashed(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = {**auth_headers(client, admin), "X-Organization-Id": "not-a-uuid"}
    response = client.get("/api/v1/organizations/current", headers=headers)
    assert response.status_code == 403


def test_membership_in_two_organizations_requires_an_explicit_choice(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from serviceflow.db.models.enums import MembershipStatus
    from serviceflow.db.models.membership import OrganizationMembership

    admin = make_user(db, organization, role=Role.ADMIN)
    second = make_organization(db, name="Second Shop")
    db.add(
        OrganizationMembership(
            organization_id=second.id,
            user_id=admin.id,
            role=Role.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
    )
    db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "test-password-123"},
    )
    bare = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/organizations/current", headers=bare).status_code == 403

    scoped = {**bare, "X-Organization-Id": str(second.id)}
    response = client.get("/api/v1/organizations/current", headers=scoped)
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(second.id)
