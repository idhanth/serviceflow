"""Customer endpoints and the customer/admin access boundary."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import auth_headers, make_customer, make_user


def test_admin_adds_a_customer(client: TestClient, db: Session, organization: Organization) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    response = client.post(
        "/api/v1/customers",
        headers=auth_headers(client, admin),
        json={
            "email": "New.Person@Example.com",
            "first_name": "New",
            "last_name": "Person",
            "phone": "+1 (415) 555-0100",
            "notes": "Prefers mornings.",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["user"]["email"] == "new.person@example.com"  # normalized
    assert data["user"]["full_name"] == "New Person"
    assert data["notes"] == "Prefers mornings."
    assert data["vehicle_count"] == 0


def test_adding_the_same_person_twice_is_rejected(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    payload = {"email": "dup@example.com", "first_name": "Dup", "last_name": "Licate"}

    assert client.post("/api/v1/customers", headers=headers, json=payload).status_code == 201
    second = client.post("/api/v1/customers", headers=headers, json=payload)
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "VALIDATION_FAILED"


def test_customers_cannot_list_or_read_other_customers(
    client: TestClient, db: Session, organization: Organization
) -> None:
    other = make_customer(db, organization, email="other@example.com", first_name="Other")
    mine = make_customer(db, organization, email="mine@example.com", first_name="Mine")
    user = db.get(type(mine.user), mine.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    assert client.get("/api/v1/customers", headers=headers).status_code == 403
    assert client.get(f"/api/v1/customers/{other.id}", headers=headers).status_code == 403
    # Not even their own record through the admin route.
    assert client.get(f"/api/v1/customers/{mine.id}", headers=headers).status_code == 403


def test_customer_reads_own_profile_via_me(
    client: TestClient, db: Session, organization: Organization
) -> None:
    make_customer(db, organization, email="other@example.com")
    mine = make_customer(db, organization, email="mine@example.com", first_name="Mine")
    user = db.get(type(mine.user), mine.user_id)
    assert user is not None

    response = client.get("/api/v1/customers/me", headers=auth_headers(client, user))
    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(mine.id)


def test_me_is_404_for_someone_with_no_customer_record(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    response = client.get("/api/v1/customers/me", headers=auth_headers(client, admin))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_admin_updates_customer_details_and_can_clear_notes(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    customer = make_customer(db, organization, notes="Original note")
    headers = auth_headers(client, admin)

    renamed = client.patch(
        f"/api/v1/customers/{customer.id}", headers=headers, json={"first_name": "Renamed"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["user"]["first_name"] == "Renamed"
    # An omitted field must not wipe the note.
    assert renamed.json()["data"]["notes"] == "Original note"

    cleared = client.patch(
        f"/api/v1/customers/{customer.id}", headers=headers, json={"notes": None}
    )
    assert cleared.json()["data"]["notes"] is None


def test_customer_search_matches_name_email_and_phone(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    make_customer(
        db, organization, email="ada.lovelace@example.com", first_name="Ada", last_name="Lovelace"
    )
    make_customer(
        db, organization, email="grace.hopper@example.com", first_name="Grace", last_name="Hopper"
    )
    headers = auth_headers(client, admin)

    by_first = client.get("/api/v1/customers?q=ada", headers=headers).json()
    assert by_first["meta"]["total"] == 1
    by_email = client.get("/api/v1/customers?q=hopper@example", headers=headers).json()
    assert by_email["meta"]["total"] == 1
    by_full = client.get("/api/v1/customers?q=Grace%20Hopper", headers=headers).json()
    assert by_full["meta"]["total"] == 1
