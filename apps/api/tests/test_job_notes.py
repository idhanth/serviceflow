"""Job notes, and the boundary that keeps INTERNAL notes away from customers."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.job_note import JobNote
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    auth_headers,
    job_with_parties,
    make_customer,
    make_employee,
    make_job_note,
    make_organization,
    make_user,
)

INTERNAL_TEXT = "Customer is a nightmare, budget extra time."
VISIBLE_TEXT = "We treated the swirl marks on the driver's door."


def _post(client: TestClient, headers: dict, job_id, content: str, visibility: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/jobs/{job_id}/notes",
        headers=headers,
        json={"content": content, "visibility": visibility},
    )


def test_assigned_employee_creates_an_internal_note(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    response = _post(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        INTERNAL_TEXT,
        "INTERNAL",
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["visibility"] == "INTERNAL"
    assert data["author_name"] == parties["employee"].user.full_name


def test_assigned_employee_creates_a_customer_visible_note(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    response = _post(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        VISIBLE_TEXT,
        "CUSTOMER_VISIBLE",
    )
    assert response.status_code == 201
    assert response.json()["data"]["visibility"] == "CUSTOMER_VISIBLE"


def test_a_customer_sees_only_the_notes_meant_for_them(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    employee_user, job = parties["employee_user"], parties["job"]
    staff = auth_headers(client, employee_user)
    _post(client, staff, job.id, INTERNAL_TEXT, "INTERNAL")
    _post(client, staff, job.id, VISIBLE_TEXT, "CUSTOMER_VISIBLE")

    response = client.get(
        f"/api/v1/jobs/{job.id}/notes", headers=auth_headers(client, parties["customer_user"])
    )
    assert response.status_code == 200
    rows = response.json()["data"]

    assert [row["content"] for row in rows] == [VISIBLE_TEXT]
    assert all(row["visibility"] == "CUSTOMER_VISIBLE" for row in rows)
    # The internal text must not appear anywhere in the payload.
    assert INTERNAL_TEXT not in response.text


def test_staff_see_both_kinds(client: TestClient, db: Session, organization: Organization) -> None:
    parties = job_with_parties(db, organization)
    admin = make_user(db, organization, role=Role.ADMIN)
    staff = auth_headers(client, parties["employee_user"])
    _post(client, staff, parties["job"].id, INTERNAL_TEXT, "INTERNAL")
    _post(client, staff, parties["job"].id, VISIBLE_TEXT, "CUSTOMER_VISIBLE")

    for headers in (staff, auth_headers(client, admin)):
        rows = client.get(f"/api/v1/jobs/{parties['job'].id}/notes", headers=headers).json()["data"]
        assert {row["visibility"] for row in rows} == {"INTERNAL", "CUSTOMER_VISIBLE"}


def test_an_internal_note_never_reaches_the_customers_booking_payload(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The nested job summary a customer reads must not carry internal content."""
    parties = job_with_parties(db, organization)
    _post(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        INTERNAL_TEXT,
        "INTERNAL",
    )
    customer_headers = auth_headers(client, parties["customer_user"])

    detail = client.get(f"/api/v1/bookings/{parties['booking'].id}", headers=customer_headers)
    listing = client.get("/api/v1/bookings?page_size=50", headers=customer_headers)

    assert INTERNAL_TEXT not in detail.text
    assert INTERNAL_TEXT not in listing.text


def test_another_customer_cannot_reach_the_notes(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    _post(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        VISIBLE_TEXT,
        "CUSTOMER_VISIBLE",
    )
    stranger = make_customer(db, organization, email="stranger@example.com")
    stranger_user = db.get(type(stranger.user), stranger.user_id)
    assert stranger_user is not None

    response = client.get(
        f"/api/v1/jobs/{parties['job'].id}/notes", headers=auth_headers(client, stranger_user)
    )
    assert response.status_code == 404


def test_an_unrelated_employee_can_neither_read_nor_write_notes(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    colleague = make_employee(db, organization, email="colleague@example.com")
    colleague_user = db.get(type(colleague.user), colleague.user_id)
    assert colleague_user is not None
    headers = auth_headers(client, colleague_user)
    note = make_job_note(
        db, organization, parties["job"], parties["employee"].user, content=INTERNAL_TEXT
    )

    assert client.get(f"/api/v1/jobs/{parties['job'].id}/notes", headers=headers).status_code == 404
    assert _post(client, headers, parties["job"].id, "sneaky", "INTERNAL").status_code == 404
    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/notes/{note.id}", headers=headers
        ).status_code
        == 404
    )
    assert db.query(JobNote).count() == 1


def test_a_customer_cannot_write_notes(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    response = _post(
        client,
        auth_headers(client, parties["customer_user"]),
        parties["job"].id,
        "let me in",
        "CUSTOMER_VISIBLE",
    )
    assert response.status_code == 403
    assert db.query(JobNote).count() == 0


def test_notes_are_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    rival = make_organization(db, name="Rival Detailing")
    rival_parties = job_with_parties(db, rival)
    note = make_job_note(
        db, rival, rival_parties["job"], rival_parties["employee"].user, content=INTERNAL_TEXT
    )
    headers = auth_headers(client, admin)

    assert (
        client.get(f"/api/v1/jobs/{rival_parties['job'].id}/notes", headers=headers).status_code
        == 404
    )
    assert _post(client, headers, rival_parties["job"].id, "x", "INTERNAL").status_code == 404
    assert (
        client.delete(
            f"/api/v1/jobs/{rival_parties['job'].id}/notes/{note.id}", headers=headers
        ).status_code
        == 404
    )
    assert db.query(JobNote).count() == 1


def test_an_invalid_visibility_is_rejected(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    response = _post(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        "text",
        "EVERYONE",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_a_blank_note_is_rejected(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    response = _post(
        client, auth_headers(client, parties["employee_user"]), parties["job"].id, "   ", "INTERNAL"
    )
    assert response.status_code == 422
    assert db.query(JobNote).count() == 0


def test_an_author_removes_their_own_note_but_not_a_colleagues(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    admin = make_user(db, organization, role=Role.ADMIN)
    staff = auth_headers(client, parties["employee_user"])

    mine = _post(client, staff, parties["job"].id, "mine", "INTERNAL").json()["data"]
    theirs = make_job_note(db, organization, parties["job"], admin, content="admin note")

    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/notes/{mine['id']}", headers=staff
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/notes/{theirs.id}", headers=staff
        ).status_code
        == 403
    )
    # An admin may remove anything in their organization.
    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/notes/{theirs.id}",
            headers=auth_headers(client, admin),
        ).status_code
        == 204
    )


def test_notes_are_newest_first(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    for index in range(3):
        _post(client, staff, parties["job"].id, f"note {index}", "INTERNAL")

    rows = client.get(f"/api/v1/jobs/{parties['job'].id}/notes", headers=staff).json()["data"]
    assert [row["content"] for row in rows] == ["note 2", "note 1", "note 0"]
