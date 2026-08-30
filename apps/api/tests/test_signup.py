"""Customer self-signup - the entry point of the PRD 62 flow."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import future_start, make_customer, make_service


def test_signup_creates_a_usable_customer_account(
    client: TestClient, db: Session, organization: Organization
) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "New.Signup@Example.com",
            "password": "a-good-password",
            "first_name": "New",
            "last_name": "Signup",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "new.signup@example.com"
    assert body["user"]["memberships"][0]["role"] == Role.CUSTOMER.value
    assert body["access_token"]

    # The token works immediately, and a customer profile exists.
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/api/v1/customers/me", headers=headers)
    assert me.status_code == 200
    assert db.query(Customer).filter_by(organization_id=organization.id).count() == 1


def test_a_new_signup_can_book_immediately(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Signing up must actually reach the bookable state PRD 62 assumes."""
    service = make_service(db, organization, name="Full Detail", duration_minutes=150)
    signup = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "booker@example.com",
            "password": "a-good-password",
            "first_name": "Book",
            "last_name": "Er",
        },
    ).json()
    headers = {"Authorization": f"Bearer {signup['access_token']}"}

    vehicle = client.post(
        "/api/v1/vehicles",
        headers=headers,
        json={"year": 2024, "make": "Tesla", "model": "Model 3"},
    )
    assert vehicle.status_code == 201

    booking = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "vehicle_id": vehicle.json()["data"]["id"],
            "service_id": str(service.id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert booking.status_code == 201
    assert booking.json()["data"]["status"] == "PENDING"


def test_signup_refuses_an_email_that_is_already_registered(
    client: TestClient, db: Session, organization: Organization
) -> None:
    make_customer(db, organization, email="taken@example.com")
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "taken@example.com",
            "password": "a-good-password",
            "first_name": "Imposter",
            "last_name": "Person",
        },
    )
    assert response.status_code == 422
    # Generic wording: signup must not confirm which addresses have accounts.
    assert "sign in instead" in response.json()["error"]["message"]


def test_signup_refuses_an_unknown_organization(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": "no-such-shop",
            "email": "someone@example.com",
            "password": "a-good-password",
            "first_name": "Some",
            "last_name": "One",
        },
    )
    assert response.status_code == 404


def test_signup_requires_a_reasonable_password(
    client: TestClient, organization: Organization
) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "short@example.com",
            "password": "abc",
            "first_name": "Short",
            "last_name": "Pass",
        },
    )
    assert response.status_code == 422


def test_signup_does_not_grant_staff_access(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A self-registered account is a customer and nothing more."""
    token = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "curious@example.com",
            "password": "a-good-password",
            "first_name": "Curious",
            "last_name": "User",
        },
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/customers", headers=headers).status_code == 403
    assert client.get("/api/v1/employees", headers=headers).status_code == 403
    assert client.get("/api/v1/jobs", headers=headers).status_code == 403
