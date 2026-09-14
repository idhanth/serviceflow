"""Service catalog endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from tests.conftest import auth_headers, make_customer, make_service, make_user


def test_admin_creates_a_service(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    response = client.post(
        "/api/v1/services",
        headers=auth_headers(client, admin),
        json={
            "name": "Ceramic Coating",
            "description": "Nine-month coating.",
            "base_price": "1200.00",
            "duration_minutes": 480,
        },
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["name"] == "Ceramic Coating"
    assert body["duration_minutes"] == 480
    assert body["active"] is True


def test_duplicate_service_name_is_rejected_per_organization(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_service(db, organization, name="Full Detail")

    response = client.post(
        "/api/v1/services",
        headers=auth_headers(client, admin),
        json={"name": "Full Detail", "base_price": "310.00", "duration_minutes": 240},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_non_admins_cannot_change_the_catalog(
    client: TestClient, db: Session, organization: Organization
) -> None:
    make_customer(db, organization, email="shopper@example.com")
    customer = make_user(db, organization, role=Role.CUSTOMER, email="writer@example.com")
    service = make_service(db, organization)
    headers = auth_headers(client, customer)

    assert (
        client.post(
            "/api/v1/services",
            headers=headers,
            json={"name": "Sneaky", "base_price": "1.00", "duration_minutes": 10},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/services/{service.id}", headers=headers, json={"base_price": "0.01"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/services/{service.id}", headers=headers).status_code == 403


def test_customers_only_see_active_services(
    client: TestClient, db: Session, organization: Organization
) -> None:
    make_service(db, organization, name="Express Wash")
    retired = make_service(db, organization, name="Retired Package", active=False)
    customer = make_user(db, organization, role=Role.CUSTOMER)
    headers = auth_headers(client, customer)

    listing = client.get("/api/v1/services", headers=headers).json()
    names = {item["name"] for item in listing["data"]}
    assert names == {"Express Wash"}

    # The active filter is ignored for non-admins: asking for inactive services
    # returns the active ones rather than widening what a customer can see.
    forced = client.get("/api/v1/services?active=false", headers=headers).json()
    assert retired.name not in {item["name"] for item in forced["data"]}
    assert client.get(f"/api/v1/services/{retired.id}", headers=headers).status_code == 404


def test_delete_deactivates_rather_than_destroying(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    service = make_service(db, organization)
    headers = auth_headers(client, admin)

    response = client.delete(f"/api/v1/services/{service.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["active"] is False

    # Still readable by an admin, so future bookings keep their history.
    assert client.get(f"/api/v1/services/{service.id}", headers=headers).status_code == 200


def test_search_and_pagination(client: TestClient, db: Session, organization: Organization) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    for name in ["Express Wash", "Interior Detail", "Exterior Detail", "Full Detail"]:
        make_service(db, organization, name=name)
    headers = auth_headers(client, admin)

    search = client.get("/api/v1/services?q=detail", headers=headers).json()
    assert search["meta"]["total"] == 3

    page = client.get("/api/v1/services?page=2&page_size=2", headers=headers).json()
    assert page["meta"] == {"page": 2, "page_size": 2, "total": 4, "pages": 2}
    assert len(page["data"]) == 2


def test_search_wildcards_are_escaped(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_service(db, organization, name="Express Wash")
    headers = auth_headers(client, admin)

    # A bare "%" would match everything if it were not escaped.
    result = client.get("/api/v1/services?q=%25", headers=headers).json()
    assert result["meta"]["total"] == 0
