from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import TEST_PASSWORD, auth_headers, make_user


def test_login_returns_token_and_memberships(
    client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["memberships"][0]["organization_id"] == str(organization.id)


def test_login_rejects_wrong_password_without_revealing_the_account(
    client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    wrong = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "not-the-password"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.json()["error"]["code"] == "UNAUTHORIZED"


def test_me_requires_a_bearer_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_me_rejects_a_tampered_token(
    client: TestClient, db: Session, organization: Organization
) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, user)
    headers["Authorization"] = headers["Authorization"][:-3] + "aaa"
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_errors_carry_a_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.json()["error"]["request_id"].startswith("req_")
    assert response.headers["x-request-id"]
