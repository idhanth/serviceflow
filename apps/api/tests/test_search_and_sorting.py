"""Sorting, pagination boundaries and global search (PRD 24, 32)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.core.pagination import parse_sort
from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_booking,
    make_customer,
    make_employee,
    make_organization,
    make_service,
    make_user,
)

# ------------------------------------------------------------------ sort parsing


@pytest.mark.parametrize(
    ("raw", "key", "descending"),
    [
        ("name", "name", False),
        ("-name", "name", True),
        (None, "name", False),
        ("", "name", False),
        ("  -name ", "name", True),
        ("nonsense", "name", False),
        ("-nonsense", "name", False),
        ("id; DROP TABLE users", "name", False),
    ],
)
def test_sort_parsing_falls_back_to_the_default(
    raw: str | None, key: str, descending: bool
) -> None:
    """Unknown keys never reach SQL; they resolve to the default."""
    spec = parse_sort(raw, allowed=frozenset({"name", "created_at"}), default="name")
    assert (spec.key, spec.descending) == (key, descending)


def test_a_descending_default_is_honoured() -> None:
    spec = parse_sort(None, allowed=frozenset({"created_at"}), default="-created_at")
    assert spec.key == "created_at"
    assert spec.descending is True


# ------------------------------------------------------------------ sorting


def test_customers_sort_by_name_in_both_directions(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    for first in ("Zoe", "Aaron", "Mia"):
        make_customer(db, organization, email=f"{first.lower()}@example.com", first_name=first)
    headers = auth_headers(client, admin)

    ascending = client.get("/api/v1/customers?sort=name", headers=headers).json()["data"]
    descending = client.get("/api/v1/customers?sort=-name", headers=headers).json()["data"]

    names = [row["user"]["first_name"] for row in ascending]
    assert names == ["Aaron", "Mia", "Zoe"]
    assert [row["user"]["first_name"] for row in descending] == ["Zoe", "Mia", "Aaron"]


def test_services_sort_by_price_and_duration(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_service(db, organization, name="Cheap Quick", price="45.00", duration_minutes=30)
    make_service(db, organization, name="Pricey Slow", price="900.00", duration_minutes=480)
    make_service(db, organization, name="Middle", price="200.00", duration_minutes=120)
    headers = auth_headers(client, admin)

    by_price = client.get("/api/v1/services?sort=price", headers=headers).json()["data"]
    assert [row["name"] for row in by_price] == ["Cheap Quick", "Middle", "Pricey Slow"]

    by_duration_desc = client.get("/api/v1/services?sort=-duration", headers=headers).json()["data"]
    assert [row["name"] for row in by_duration_desc] == ["Pricey Slow", "Middle", "Cheap Quick"]


def test_employees_sort_by_job_title_with_active_first(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_employee(db, organization, email="a@example.com", job_title="Zebra Wrangler")
    make_employee(db, organization, email="b@example.com", job_title="Apprentice")
    make_employee(db, organization, email="c@example.com", job_title="Alpha", active=False)

    rows = client.get(
        "/api/v1/employees?sort=job_title", headers=auth_headers(client, admin)
    ).json()["data"]
    assert [row["job_title"] for row in rows] == ["Apprentice", "Zebra Wrangler", "Alpha"]


def test_an_unknown_sort_key_is_ignored_rather_than_erroring(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_customer(db, organization)
    response = client.get(
        "/api/v1/customers?sort=%27%3B+DROP+TABLE+users%3B--", headers=auth_headers(client, admin)
    )
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1


# ------------------------------------------------------------------ pagination


def test_pagination_boundaries(client: TestClient, db: Session, organization: Organization) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    for index in range(7):
        make_customer(db, organization, email=f"c{index}@example.com", first_name=f"C{index}")
    headers = auth_headers(client, admin)

    first = client.get("/api/v1/customers?page=1&page_size=3", headers=headers).json()
    assert first["meta"] == {"page": 1, "page_size": 3, "total": 7, "pages": 3}
    last = client.get("/api/v1/customers?page=3&page_size=3", headers=headers).json()
    assert len(last["data"]) == 1

    # Past the end is empty, not an error.
    beyond = client.get("/api/v1/customers?page=99&page_size=3", headers=headers).json()
    assert beyond["data"] == []
    assert beyond["meta"]["total"] == 7

    # Every row appears exactly once across the pages.
    seen = []
    for page in (1, 2, 3):
        seen += [
            row["id"]
            for row in client.get(
                f"/api/v1/customers?page={page}&page_size=3", headers=headers
            ).json()["data"]
        ]
    assert len(seen) == len(set(seen)) == 7


@pytest.mark.parametrize(
    "query", ["page=0", "page=-1", "page_size=0", "page_size=101", "page_size=-5", "page=abc"]
)
def test_invalid_pagination_parameters_are_refused(
    client: TestClient, db: Session, organization: Organization, query: str
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    response = client.get(f"/api/v1/customers?{query}", headers=auth_headers(client, admin))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# ------------------------------------------------------------------ collection search


def test_bookings_search_by_customer_and_service(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, admin)

    assert client.get("/api/v1/bookings?q=Booker", headers=headers).json()["meta"]["total"] == 1
    assert (
        client.get("/api/v1/bookings?q=HVAC%20Repair", headers=headers).json()["meta"]["total"] == 1
    )
    assert (
        client.get("/api/v1/bookings?q=nothingmatches", headers=headers).json()["meta"]["total"]
        == 0
    )


def test_jobs_search_is_still_scoped_to_the_employee(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    colleague = make_employee(db, organization, email="colleague@example.com")
    other = job_with_parties(db, organization)
    other["job"].employee_id = colleague.id
    db.commit()

    rows = client.get(
        "/api/v1/jobs?q=Booker", headers=auth_headers(client, parties["employee_user"])
    ).json()
    assert rows["meta"]["total"] == 1
    assert rows["data"][0]["id"] == str(parties["job"].id)


def test_bookings_sort_by_created_at(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    for offset in (3, 9, 6):
        make_booking(
            db,
            organization,
            setup["customer"],
            setup["service"],
            start=future_start(days=offset),
        )

    rows = client.get(
        "/api/v1/bookings?sort=requested_start", headers=auth_headers(client, admin)
    ).json()["data"]
    starts = [row["requested_start"] for row in rows]
    assert starts == sorted(starts)


# ------------------------------------------------------------------ global search


def test_global_search_spans_the_record_types(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )

    rows = client.get("/api/v1/search?q=Booker", headers=auth_headers(client, admin)).json()["data"]
    kinds = {row["kind"] for row in rows}
    assert "customer" in kinds
    assert "booking" in kinds
    assert all(row["href"] for row in rows)


def test_global_search_never_crosses_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    rival = make_organization(db, name="Rival Detailing")
    make_customer(db, rival, email="rival-target@example.com", first_name="Rivaltarget")
    make_service(db, rival, name="Rivaltarget Wash")

    response = client.get("/api/v1/search?q=Rivaltarget", headers=auth_headers(client, admin))
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert "Rivaltarget" not in response.text


def test_a_short_term_returns_nothing(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_customer(db, organization, first_name="Alice")
    headers = auth_headers(client, admin)

    assert client.get("/api/v1/search?q=A", headers=headers).json()["data"] == []
    assert client.get("/api/v1/search", headers=headers).json()["data"] == []


def test_search_wildcards_are_escaped(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_customer(db, organization, first_name="Alice")
    rows = client.get("/api/v1/search?q=%25%25", headers=auth_headers(client, admin)).json()["data"]
    assert rows == []


def test_only_admins_can_use_global_search(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    for user in (parties["customer_user"], parties["employee_user"]):
        response = client.get("/api/v1/search?q=Booker", headers=auth_headers(client, user))
        assert response.status_code == 403
