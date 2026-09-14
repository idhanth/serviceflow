"""The seven-role permission matrix, exercised through the real API.

Each row is an endpoint and the set of tenant roles whose request gets past
authorization. Everyone else must receive 403 INVALID_ROLE. "Gets past" means
anything but 403: an allowed caller may still see 404 or 422 for other reasons.
The platform administrator, who holds no membership, is covered separately.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    make_booking,
    make_employee,
    make_user,
)

OWN, MAN, DIS, TEC, CUS, ANA = (
    Role.OWNER,
    Role.MANAGER,
    Role.DISPATCHER,
    Role.TECHNICIAN,
    Role.CUSTOMER,
    Role.ANALYST,
)

# (method, path template, body factory, roles allowed past authorization)
MATRIX = [
    ("GET", "/api/v1/dashboard", None, {OWN, MAN, DIS, ANA}),
    ("GET", "/api/v1/customers", None, {OWN, MAN, DIS, ANA}),
    ("POST", "/api/v1/customers", "customer", {OWN, MAN, DIS}),
    ("DELETE", "/api/v1/customers/{customer}", None, {OWN, MAN}),
    ("GET", "/api/v1/employees", None, {OWN, MAN, DIS, ANA}),
    ("POST", "/api/v1/employees", "employee", {OWN, MAN}),
    ("POST", "/api/v1/services", "service", {OWN, MAN}),
    ("GET", "/api/v1/bookings", None, {OWN, MAN, DIS, ANA, CUS}),
    ("POST", "/api/v1/bookings", "booking", {OWN, MAN, DIS, CUS}),
    ("POST", "/api/v1/bookings/{booking}/reject", "empty", {OWN, MAN, DIS}),
    ("GET", "/api/v1/jobs", None, {OWN, MAN, DIS, ANA, TEC}),
    ("POST", "/api/v1/jobs/{job}/assign", "assign", {OWN, MAN, DIS}),
    ("POST", "/api/v1/jobs/{job}/cancel", None, {OWN, MAN, DIS}),
    ("GET", "/api/v1/schedule?start=2031-01-06", None, {OWN, MAN, DIS, ANA, TEC}),
    ("GET", "/api/v1/activity", None, {OWN, MAN, ANA}),
    ("GET", "/api/v1/members", None, {OWN, MAN, ANA}),
    ("POST", "/api/v1/members", "member", {OWN}),
    ("PATCH", "/api/v1/organizations/current", "settings", {OWN}),
    ("GET", "/api/v1/search?q=test", None, {OWN, MAN, DIS, ANA}),
    ("GET", "/api/v1/platform/tenants", None, set()),
]


def _body(kind: str | None, setup: dict) -> dict | None:  # type: ignore[type-arg]
    return {
        None: None,
        "empty": {},
        "customer": {"email": "matrix-new@example.com", "first_name": "New", "last_name": "Person"},
        "employee": {"email": "matrix-tech@example.com", "first_name": "New", "last_name": "Tech"},
        "service": {"name": "Matrix Service", "base_price": "99.00", "duration_minutes": 60},
        "booking": {
            "customer_id": str(setup["customer"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start(days=20).isoformat(),
        },
        "assign": {"employee_id": str(setup["employee"].id)},
        "member": {
            "email": "matrix-member@example.com",
            "first_name": "M",
            "last_name": "M",
            "role": "ANALYST",
        },
        "settings": {"phone": "+1 (847) 555-0100"},
    }[kind]


@pytest.mark.parametrize("role", [OWN, MAN, DIS, TEC, CUS, ANA], ids=lambda role: role.value)
def test_every_role_gets_exactly_its_permissions(
    client: TestClient, db: Session, organization: Organization, role: Role
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    job_id = str(booking.job.id) if booking.job else ""  # type: ignore[union-attr]
    if role is Role.TECHNICIAN:
        caller = setup["employee_user"]
    elif role is Role.CUSTOMER:
        caller = setup["customer_user"]
    else:
        caller = make_user(db, organization, role=role)
    headers = auth_headers(client, caller)

    wrong = []
    for method, template, body, allowed in MATRIX:
        path = template.format(customer=setup["customer"].id, booking=booking.id, job=job_id)
        response = client.request(method, path, headers=headers, json=_body(body, setup))
        refused = response.status_code == 403
        if (role in allowed) == refused:
            wrong.append(f"{method} {template}: {response.status_code} {response.text[:120]}")
        if refused and "platform" not in template:
            assert response.json()["error"]["code"] in {"INVALID_ROLE", "FORBIDDEN"}
    assert not wrong, f"{role.value} saw the wrong authorization result:\n" + "\n".join(wrong)


def test_a_technician_can_act_on_their_own_job_but_not_a_colleagues(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    colleague = make_employee(
        db, organization, email="colleague@example.com", services=[setup["service"]]
    )
    mine = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
        employee=setup["employee"],
    )
    theirs = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
        employee=colleague,
        start=future_start(days=5),
    )
    headers = auth_headers(client, setup["employee_user"])

    assert client.post(f"/api/v1/jobs/{mine.job.id}/start", headers=headers).status_code == 200  # type: ignore[union-attr]
    # A colleague's job reads as missing, not merely forbidden.
    assert client.post(f"/api/v1/jobs/{theirs.job.id}/start", headers=headers).status_code == 404  # type: ignore[union-attr]
    assert client.get(f"/api/v1/jobs/{theirs.job.id}", headers=headers).status_code == 404  # type: ignore[union-attr]


def test_an_analyst_reads_everything_and_changes_nothing(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
        employee=setup["employee"],
    )
    analyst = make_user(db, organization, role=Role.ANALYST)
    headers = auth_headers(client, analyst)

    assert client.get(f"/api/v1/bookings/{booking.id}", headers=headers).status_code == 200
    job = client.get(f"/api/v1/jobs/{booking.job.id}", headers=headers)  # type: ignore[union-attr]
    assert job.status_code == 200
    for method, path, body in [
        ("POST", f"/api/v1/jobs/{booking.job.id}/start", None),  # type: ignore[union-attr]
        ("PATCH", f"/api/v1/jobs/{booking.job.id}", {"internal_notes": "x"}),  # type: ignore[union-attr]
        ("POST", f"/api/v1/bookings/{booking.id}/cancel", {}),
        ("PATCH", f"/api/v1/customers/{setup['customer'].id}", {"notes": "x"}),
        (
            "POST",
            f"/api/v1/jobs/{booking.job.id}/notes",
            {"content": "x", "visibility": "INTERNAL"},
        ),  # type: ignore[union-attr]
    ]:
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
