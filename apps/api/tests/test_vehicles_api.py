"""Vehicle endpoints - the sharpest customer-vs-customer boundary in phase 2."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle
from tests.conftest import auth_headers, make_customer, make_user, make_vehicle


def test_customer_adds_and_lists_only_their_own_vehicles(
    client: TestClient, db: Session, organization: Organization
) -> None:
    mine = make_customer(db, organization, email="mine@example.com")
    theirs = make_customer(db, organization, email="theirs@example.com")
    make_vehicle(db, organization, theirs, make="Porsche", model="911")

    user = db.get(User, mine.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    created = client.post(
        "/api/v1/vehicles",
        headers=headers,
        json={"year": 2023, "make": "Tesla", "model": "Model Y", "license_plate": "abc123"},
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["customer_id"] == str(mine.id)
    assert data["license_plate"] == "ABC123"  # normalized
    assert data["display_name"] == "2023 Tesla Model Y"
    assert data["owner"] is None  # customers do not get owner metadata

    listing = client.get("/api/v1/vehicles", headers=headers).json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["make"] == "Tesla"


def test_customer_cannot_read_another_customers_vehicle(
    client: TestClient, db: Session, organization: Organization
) -> None:
    mine = make_customer(db, organization, email="mine@example.com")
    theirs = make_customer(db, organization, email="theirs@example.com")
    their_vehicle = make_vehicle(db, organization, theirs)

    user = db.get(User, mine.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    # 404 rather than 403: ids must not be probeable.
    assert client.get(f"/api/v1/vehicles/{their_vehicle.id}", headers=headers).status_code == 404
    assert (
        client.patch(
            f"/api/v1/vehicles/{their_vehicle.id}", headers=headers, json={"color": "Pink"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/vehicles/{their_vehicle.id}", headers=headers).status_code == 404


def test_customer_cannot_filter_to_another_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    mine = make_customer(db, organization, email="mine@example.com")
    theirs = make_customer(db, organization, email="theirs@example.com")
    make_vehicle(db, organization, theirs)

    user = db.get(User, mine.user_id)
    assert user is not None
    response = client.get(
        f"/api/v1/vehicles?customer_id={theirs.id}", headers=auth_headers(client, user)
    )
    assert response.status_code == 403


def test_customer_cannot_assign_a_vehicle_to_someone_else(
    client: TestClient, db: Session, organization: Organization
) -> None:
    mine = make_customer(db, organization, email="mine@example.com")
    theirs = make_customer(db, organization, email="theirs@example.com")

    user = db.get(User, mine.user_id)
    assert user is not None
    response = client.post(
        "/api/v1/vehicles",
        headers=auth_headers(client, user),
        json={"customer_id": str(theirs.id), "year": 2020, "make": "Kia", "model": "Telluride"},
    )
    assert response.status_code == 403


def test_admin_sees_every_vehicle_with_owner_details(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    one = make_customer(db, organization, email="one@example.com", first_name="One")
    two = make_customer(db, organization, email="two@example.com", first_name="Two")
    make_vehicle(db, organization, one, make="Audi", model="Q5")
    make_vehicle(db, organization, two, make="Volvo", model="XC90")
    headers = auth_headers(client, admin)

    listing = client.get("/api/v1/vehicles", headers=headers).json()
    assert listing["meta"]["total"] == 2
    assert all(item["owner"]["full_name"] for item in listing["data"])

    scoped = client.get(f"/api/v1/vehicles?customer_id={one.id}", headers=headers).json()
    assert scoped["meta"]["total"] == 1
    assert scoped["data"][0]["make"] == "Audi"


def test_admin_adds_a_vehicle_for_a_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    customer = make_customer(db, organization)

    response = client.post(
        "/api/v1/vehicles",
        headers=auth_headers(client, admin),
        json={
            "customer_id": str(customer.id),
            "year": 2021,
            "make": "BMW",
            "model": "M3",
            "color": "Alpine White",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["customer_id"] == str(customer.id)


def test_vehicle_search_and_year_validation(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    customer = make_customer(db, organization)
    make_vehicle(db, organization, customer, make="Tesla", model="Model 3", license_plate="XYZ789")
    make_vehicle(db, organization, customer, make="Ford", model="Bronco")
    headers = auth_headers(client, admin)

    by_make = client.get("/api/v1/vehicles?q=tesla", headers=headers).json()
    assert by_make["meta"]["total"] == 1
    by_plate = client.get("/api/v1/vehicles?q=XYZ", headers=headers).json()
    assert by_plate["meta"]["total"] == 1

    bad_year = client.post(
        "/api/v1/vehicles",
        headers=headers,
        json={"customer_id": str(customer.id), "year": 1850, "make": "Horse", "model": "Cart"},
    )
    assert bad_year.status_code == 422
    assert bad_year.json()["error"]["details"]["fields"]["year"]


def test_removing_a_vehicle_archives_it_rather_than_deleting(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Bookings and jobs reference vehicles, so the row has to survive."""
    customer = make_customer(db, organization)
    vehicle = make_vehicle(db, organization, customer)
    user = db.get(User, customer.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    response = client.delete(f"/api/v1/vehicles/{vehicle.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["archived"] is True

    # Gone from the customer's garage and no longer individually readable...
    assert client.get("/api/v1/vehicles", headers=headers).json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/vehicles/{vehicle.id}", headers=headers).status_code == 404

    # ...but the row is still there for anything that references it.
    db.expire_all()
    stored = db.get(Vehicle, vehicle.id)
    assert stored is not None
    assert stored.archived_at is not None


def test_archiving_is_idempotent(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A double-submitted remove must not error."""
    customer = make_customer(db, organization)
    vehicle = make_vehicle(db, organization, customer)
    user = db.get(User, customer.user_id)
    assert user is not None
    headers = auth_headers(client, user)

    first = client.delete(f"/api/v1/vehicles/{vehicle.id}", headers=headers)
    second = client.delete(f"/api/v1/vehicles/{vehicle.id}", headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json()["data"]["archived"] is True
