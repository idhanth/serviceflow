"""Photo uploads against real S3-compatible storage.

These talk to the MinIO instance the dev stack runs. Nothing is stubbed: the
presigned POST is really posted to, and the bytes really land in a bucket. A test
double here would prove nothing about the flow that ships.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import JobStatus, Role
from serviceflow.db.models.job_photo import MAX_PHOTO_BYTES, MAX_PHOTOS_PER_JOB, JobPhoto
from serviceflow.db.models.organization import Organization
from serviceflow.services.storage import get_object_storage
from tests.conftest import (
    JPEG_1PX,
    PNG_1PX,
    WEBP_1PX,
    auth_headers,
    job_with_parties,
    make_customer,
    make_employee,
    make_organization,
    make_user,
)


def presign(client: TestClient, headers: dict, job_id, mime: str, size: int):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/jobs/{job_id}/photos/presign",
        headers=headers,
        json={"mime_type": mime, "file_size": size},
    )


def put_to_storage(slot: dict, payload: bytes, mime: str) -> httpx.Response:
    """Perform the browser's half of the flow: a real multipart POST to S3."""
    return httpx.post(
        slot["url"],
        data=slot["fields"],
        files={"file": ("photo", payload, mime)},
        timeout=30,
    )


def upload(client: TestClient, headers: dict, job_id, payload: bytes, mime: str, kind="BEFORE"):  # type: ignore[no-untyped-def]
    """The whole flow: presign -> real upload -> finalize."""
    slot = presign(client, headers, job_id, mime, len(payload)).json()["data"]
    stored = put_to_storage(slot, payload, mime)
    assert stored.status_code in (200, 204), stored.text
    return client.post(
        f"/api/v1/jobs/{job_id}/photos",
        headers=headers,
        json={"storage_key": slot["storage_key"], "photo_type": kind},
    )


# ------------------------------------------------------------------ happy path


@pytest.mark.parametrize(
    ("payload", "mime"),
    [(JPEG_1PX, "image/jpeg"), (PNG_1PX, "image/png"), (WEBP_1PX, "image/webp")],
)
def test_each_allowed_image_type_uploads_end_to_end(
    client: TestClient, db: Session, organization: Organization, payload: bytes, mime: str
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    response = upload(client, headers, parties["job"].id, payload, mime)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["mime_type"] == mime
    # Size comes from the stored object, not from what the client claimed.
    assert data["file_size"] == len(payload)
    assert data["url"].startswith("http")

    # The object really is in the bucket, with the right length.
    stored = get_object_storage().head(db.query(JobPhoto).one().storage_key)
    assert stored is not None
    assert stored.size == len(payload)
    assert stored.content_type == mime


def test_the_stored_object_serves_the_exact_bytes_back(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Proof the pipeline moved real content, not a placeholder."""
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    created = upload(client, headers, parties["job"].id, PNG_1PX, "image/png").json()["data"]

    fetched = httpx.get(created["url"], timeout=30)
    assert fetched.status_code == 200
    assert fetched.content == PNG_1PX


def test_photos_group_by_type(client: TestClient, db: Session, organization: Organization) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    for kind in ("BEFORE", "AFTER", "OTHER"):
        assert (
            upload(client, headers, parties["job"].id, PNG_1PX, "image/png", kind).status_code
            == 201
        )

    rows = client.get(f"/api/v1/jobs/{parties['job'].id}/photos", headers=headers).json()["data"]
    assert {row["photo_type"] for row in rows} == {"BEFORE", "AFTER", "OTHER"}


# ------------------------------------------------------------------ validation


def test_a_disallowed_mime_type_is_refused_at_presign(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    for mime in ("application/pdf", "image/gif", "application/x-mach-binary", "text/html"):
        response = presign(client, headers, parties["job"].id, mime, 1024)
        assert response.status_code == 422, mime
        assert response.json()["error"]["details"]["fields"]["mime_type"]


def test_a_file_over_ten_megabytes_is_refused_at_presign(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    assert (
        presign(client, headers, parties["job"].id, "image/png", MAX_PHOTO_BYTES + 1).status_code
        == 422
    )
    assert presign(client, headers, parties["job"].id, "image/png", 0).status_code == 422
    # Exactly at the limit is allowed.
    assert (
        presign(client, headers, parties["job"].id, "image/png", MAX_PHOTO_BYTES).status_code == 200
    )


def test_storage_itself_rejects_a_body_bigger_than_the_signed_policy(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The size ceiling is enforced by S3, not only by the API.

    A client that understates its size at presign still cannot upload the bytes.
    """
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    slot = presign(client, headers, parties["job"].id, "image/png", 1024).json()["data"]

    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_PHOTO_BYTES + 1024)
    rejected = put_to_storage(slot, oversized, "image/png")
    assert rejected.status_code >= 400

    # ...and with nothing stored, finalize refuses too.
    finalize = client.post(
        f"/api/v1/jobs/{parties['job'].id}/photos",
        headers=headers,
        json={"storage_key": slot["storage_key"], "photo_type": "BEFORE"},
    )
    assert finalize.status_code == 400
    assert finalize.json()["error"]["code"] == "UPLOAD_FAILED"
    assert db.query(JobPhoto).count() == 0


def test_storage_rejects_a_content_type_the_policy_did_not_sign(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    slot = presign(client, headers, parties["job"].id, "image/png", len(PNG_1PX)).json()["data"]

    slot["fields"]["Content-Type"] = "application/x-executable"
    assert put_to_storage(slot, PNG_1PX, "application/x-executable").status_code >= 400


def test_finalizing_without_a_real_upload_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """No object, no metadata. This is what stops a fabricated photo record."""
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    slot = presign(client, headers, parties["job"].id, "image/png", len(PNG_1PX)).json()["data"]

    response = client.post(
        f"/api/v1/jobs/{parties['job'].id}/photos",
        headers=headers,
        json={"storage_key": slot["storage_key"], "photo_type": "BEFORE"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UPLOAD_FAILED"
    assert db.query(JobPhoto).count() == 0


def test_a_client_supplied_storage_key_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Keys are minted server-side; one pointing elsewhere must not be accepted."""
    parties = job_with_parties(db, organization)
    other = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    for forged in (
        "organizations/../../etc/passwd",
        f"organizations/{organization.id}/jobs/{other['job'].id}/photos/stolen.png",
        "arbitrary/key.png",
    ):
        response = client.post(
            f"/api/v1/jobs/{parties['job'].id}/photos",
            headers=headers,
            json={"storage_key": forged, "photo_type": "BEFORE"},
        )
        assert response.status_code == 422, forged
        assert response.json()["error"]["details"]["fields"]["storage_key"]


def test_storage_keys_are_scoped_and_unguessable(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    first = presign(client, headers, parties["job"].id, "image/png", 100).json()["data"]
    second = presign(client, headers, parties["job"].id, "image/png", 100).json()["data"]

    prefix = f"organizations/{organization.id}/jobs/{parties['job'].id}/photos/"
    assert first["storage_key"].startswith(prefix)
    assert first["storage_key"].endswith(".png")
    assert first["storage_key"] != second["storage_key"]


def test_the_presigned_slot_is_short_lived_and_capped(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    slot = presign(client, headers, parties["job"].id, "image/png", 100).json()["data"]

    assert 0 < slot["expires_in"] <= 900
    assert slot["max_bytes"] == MAX_PHOTO_BYTES
    # The signed policy is what carries the constraints to S3.
    assert "policy" in slot["fields"]
    assert slot["fields"]["Content-Type"] == "image/png"


def test_the_twelve_photo_limit_is_enforced(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    for index in range(MAX_PHOTOS_PER_JOB):
        assert (
            upload(client, headers, parties["job"].id, PNG_1PX, "image/png").status_code == 201
        ), index

    assert presign(client, headers, parties["job"].id, "image/png", 100).status_code == 422
    assert db.query(JobPhoto).count() == MAX_PHOTOS_PER_JOB


# ------------------------------------------------------------------ access


def test_the_customer_sees_their_own_jobs_photos(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    upload(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        PNG_1PX,
        "image/png",
    )

    response = client.get(
        f"/api/v1/jobs/{parties['job'].id}/photos",
        headers=auth_headers(client, parties["customer_user"]),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1


def test_a_customer_cannot_upload_or_delete(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    photo = upload(client, staff, parties["job"].id, PNG_1PX, "image/png").json()["data"]
    customer = auth_headers(client, parties["customer_user"])

    assert presign(client, customer, parties["job"].id, "image/png", 100).status_code == 403
    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/photos/{photo['id']}", headers=customer
        ).status_code
        == 403
    )


def test_another_customer_cannot_reach_the_photos(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    upload(
        client,
        auth_headers(client, parties["employee_user"]),
        parties["job"].id,
        PNG_1PX,
        "image/png",
    )
    stranger = make_customer(db, organization, email="stranger@example.com")
    stranger_user = db.get(type(stranger.user), stranger.user_id)
    assert stranger_user is not None

    assert (
        client.get(
            f"/api/v1/jobs/{parties['job'].id}/photos", headers=auth_headers(client, stranger_user)
        ).status_code
        == 404
    )


def test_an_unrelated_employee_cannot_upload_to_the_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    colleague = make_employee(db, organization, email="colleague@example.com")
    colleague_user = db.get(type(colleague.user), colleague.user_id)
    assert colleague_user is not None
    headers = auth_headers(client, colleague_user)

    assert presign(client, headers, parties["job"].id, "image/png", 100).status_code == 404
    assert (
        client.get(f"/api/v1/jobs/{parties['job'].id}/photos", headers=headers).status_code == 404
    )


def test_photos_are_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    rival = make_organization(db, name="Rival Detailing")
    rival_parties = job_with_parties(db, rival)
    upload(
        client,
        auth_headers(client, rival_parties["employee_user"], rival),
        rival_parties["job"].id,
        PNG_1PX,
        "image/png",
    )
    headers = auth_headers(client, admin)

    assert (
        client.get(f"/api/v1/jobs/{rival_parties['job'].id}/photos", headers=headers).status_code
        == 404
    )
    assert presign(client, headers, rival_parties["job"].id, "image/png", 100).status_code == 404
    assert db.query(JobPhoto).count() == 1


# ------------------------------------------------------------------ lifecycle


def test_deleting_a_photo_removes_the_row_and_the_object(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    created = upload(client, headers, parties["job"].id, PNG_1PX, "image/png").json()["data"]
    key = db.query(JobPhoto).one().storage_key
    assert get_object_storage().head(key) is not None

    response = client.delete(
        f"/api/v1/jobs/{parties['job'].id}/photos/{created['id']}", headers=headers
    )
    assert response.status_code == 204
    assert db.query(JobPhoto).count() == 0
    assert get_object_storage().head(key) is None


def test_photos_cannot_be_added_to_a_cancelled_job(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    parties["job"].status = JobStatus.CANCELLED
    db.commit()

    response = presign(
        client, auth_headers(client, parties["employee_user"]), parties["job"].id, "image/png", 100
    )
    assert response.status_code == 422


def test_an_employee_cannot_remove_a_photo_once_the_job_is_complete(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The record is fixed at completion; an admin can still correct it."""
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    created = upload(client, staff, parties["job"].id, PNG_1PX, "image/png").json()["data"]

    parties["job"].status = JobStatus.COMPLETED
    db.commit()

    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/photos/{created['id']}", headers=staff
        ).status_code
        == 422
    )
    admin = make_user(db, organization, role=Role.ADMIN)
    assert (
        client.delete(
            f"/api/v1/jobs/{parties['job'].id}/photos/{created['id']}",
            headers=auth_headers(client, admin),
        ).status_code
        == 204
    )


def test_the_same_upload_cannot_be_finalized_twice(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    slot = presign(client, headers, parties["job"].id, "image/png", len(PNG_1PX)).json()["data"]
    put_to_storage(slot, PNG_1PX, "image/png")
    body = {"storage_key": slot["storage_key"], "photo_type": "BEFORE"}

    assert (
        client.post(
            f"/api/v1/jobs/{parties['job'].id}/photos", headers=headers, json=body
        ).status_code
        == 201
    )
    second = client.post(f"/api/v1/jobs/{parties['job'].id}/photos", headers=headers, json=body)
    assert second.status_code == 422
    assert db.query(JobPhoto).count() == 1
