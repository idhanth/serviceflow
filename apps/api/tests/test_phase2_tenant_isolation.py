"""Cross-organization access attempts against every phase 2 entity (PRD 5).

Each test authenticates a legitimate admin of organization A and points them at a
resource id belonging to organization B. Nothing may leak, and the response must
not distinguish "belongs to someone else" from "does not exist".
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from tests.conftest import (
    auth_headers,
    make_customer,
    make_employee,
    make_organization,
    make_service,
    make_user,
)


@pytest.fixture()
def rival(db: Session) -> Organization:
    """A fully populated second organization the caller has no membership in."""
    org = make_organization(db, name="Rival Home Services")
    service = make_service(db, org, name="Rival Wash")
    make_customer(db, org, email="rival-customer@example.com", first_name="Rival")
    make_employee(db, org, email="rival-employee@example.com", services=[service])
    return org


def _rival_ids(db: Session, rival: Organization) -> dict[str, uuid.UUID]:
    def one(model):  # type: ignore[no-untyped-def]
        row = db.query(model).filter_by(organization_id=rival.id).first()
        assert row is not None
        return row.id

    return {
        "service": one(Service),
        "customer": one(Customer),
        "employee": one(Employee),
    }


def test_listings_never_include_another_organizations_rows(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    make_service(db, organization, name="Our Wash")
    make_customer(db, organization, email="ours@example.com", first_name="Ours")
    headers = auth_headers(client, admin)

    for path, marker in [
        ("/api/v1/services", "Rival Wash"),
        ("/api/v1/customers", "Rival"),
        ("/api/v1/employees", "rival-employee@example.com"),
    ]:
        body = client.get(f"{path}?page_size=100", headers=headers).text
        assert marker not in body, f"{path} leaked a rival organization row"


@pytest.mark.parametrize(
    ("template", "key", "expected"),
    [
        ("/api/v1/services/{}", "service", 404),
        ("/api/v1/customers/{}", "customer", 404),
        ("/api/v1/employees/{}", "employee", 404),
    ],
)
def test_reading_a_foreign_resource_by_id_is_not_found(
    client: TestClient,
    db: Session,
    organization: Organization,
    rival: Organization,
    template: str,
    key: str,
    expected: int,
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    ids = _rival_ids(db, rival)
    response = client.get(template.format(ids[key]), headers=auth_headers(client, admin))
    assert response.status_code == expected


def test_a_foreign_id_is_indistinguishable_from_a_nonexistent_one(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    ids = _rival_ids(db, rival)
    missing = uuid.uuid4()

    for template, key in [
        ("/api/v1/services/{}", "service"),
        ("/api/v1/customers/{}", "customer"),
        ("/api/v1/employees/{}", "employee"),
    ]:
        foreign = client.get(template.format(ids[key]), headers=headers)
        absent = client.get(template.format(missing), headers=headers)
        assert foreign.status_code == absent.status_code
        assert foreign.json()["error"]["code"] == absent.json()["error"]["code"]
        assert foreign.json()["error"]["message"] == absent.json()["error"]["message"]


def test_mutating_a_foreign_resource_is_refused(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    ids = _rival_ids(db, rival)

    assert (
        client.patch(
            f"/api/v1/services/{ids['service']}", headers=headers, json={"base_price": "0.01"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/customers/{ids['customer']}", headers=headers, json={"notes": "pwned"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/employees/{ids['employee']}", headers=headers, json={"active": False}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/customers/{ids['customer']}", headers=headers).status_code == 404

    # Nothing was actually written.
    rival_service = db.get(Service, ids["service"])
    assert rival_service is not None
    db.refresh(rival_service)
    assert rival_service.base_price != 0.01


def test_a_foreign_customer_cannot_be_booked_with_a_local_service(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    ours = make_service(db, organization, name="Our Inspection")
    ids = _rival_ids(db, rival)

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, admin),
        json={
            "customer_id": str(ids["customer"]),
            "service_id": str(ours.id),
            "requested_start": "2031-05-05T15:00:00+00:00",
        },
    )
    assert response.status_code == 404


def test_a_user_in_both_organizations_sees_only_the_scoped_one(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    """Membership in two organizations must not merge their data."""
    from serviceflow.db.models.enums import MembershipStatus
    from serviceflow.db.models.membership import OrganizationMembership

    admin = make_user(db, organization, role=Role.OWNER)
    db.add(
        OrganizationMembership(
            organization_id=rival.id,
            user_id=admin.id,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    db.commit()
    make_service(db, organization, name="Our Wash")

    login = client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": "test-password-123"}
    )
    token = login.json()["access_token"]

    ours = client.get(
        "/api/v1/services",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(organization.id)},
    ).json()
    theirs = client.get(
        "/api/v1/services",
        headers={"Authorization": f"Bearer {token}", "X-Organization-Id": str(rival.id)},
    ).json()

    assert {s["name"] for s in ours["data"]} == {"Our Wash"}
    assert {s["name"] for s in theirs["data"]} == {"Rival Wash"}


def test_customers_of_one_organization_are_invisible_to_the_other(
    client: TestClient, db: Session, organization: Organization, rival: Organization
) -> None:
    """The rival's own admin must not reach our records either - isolation is mutual."""
    rival_admin = make_user(db, rival, role=Role.OWNER, email="rival-admin@example.com")
    our_customer = make_customer(db, organization, email="ours@example.com", first_name="Ours")
    our_user = db.get(User, our_customer.user_id)
    assert our_user is not None

    response = client.get(
        f"/api/v1/customers/{our_customer.id}", headers=auth_headers(client, rival_admin)
    )
    assert response.status_code == 404
