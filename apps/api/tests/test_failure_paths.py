"""What happens when a dependency or a precondition gives way (PRD 53).

The PRD names the failures this system has to survive: Redis down, the email
provider down, an S3 upload failure, a transaction failure, a dropped realtime
connection, a duplicate request, lost authorization, a deactivated employee and
a deactivated service.

Several of those already have homes - the limiter's outage policy in
`test_rate_limiting.py`, delivery failures in `test_email_delivery.py`, the
realtime drop in `test_realtime.py`. This file covers the rest, and in every
case asks the same three questions: is the durable state still right, is the
message safe to show a person, and does the system recover when the dependency
returns?
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.job_photo import JobPhoto
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.main import create_app
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_booking,
    make_user,
)

FORBIDDEN_IN_A_RESPONSE = (
    "Traceback",
    "botocore",
    "psycopg",
    "sqlalchemy",
    "SELECT ",
    "/Users/",
    "site-packages",
    "X-Amz-Signature",
    "AccessKey",
)


def lenient_client() -> TestClient:
    """A client that renders the app's own 500 rather than re-raising into the test."""
    return TestClient(create_app(), raise_server_exceptions=False)


def assert_safe(text: str) -> None:
    for needle in FORBIDDEN_IN_A_RESPONSE:
        assert needle not in text, f"{needle!r} leaked into a response"


# ------------------------------------------------------------ object storage


def test_a_presign_fails_cleanly_when_object_storage_is_unreachable(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    from serviceflow.services import photos

    parties = job_with_parties(db, organization)

    class Unreachable:
        def presign_upload(self, **_: Any) -> None:
            raise OSError("Could not connect to the endpoint URL: http://127.0.0.1:9000")

    monkeypatch.setattr(photos, "get_object_storage", lambda: Unreachable())

    headers = auth_headers(client, parties["employee_user"])
    with lenient_client() as strict:
        response = strict.post(
            f"/api/v1/jobs/{parties['job'].id}/photos/presign",
            headers=headers,
            json={"mime_type": "image/png", "file_size": 1024},
        )

    assert response.status_code >= 500
    assert_safe(response.text)
    assert "9000" not in response.text
    assert response.json()["error"]["request_id"].startswith("req_")
    # Nothing was recorded for an upload that never happened.
    assert db.query(JobPhoto).count() == 0


def test_no_photo_row_is_written_when_the_object_is_not_really_there(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metadata follows the object, never the client's word for it."""
    from serviceflow.services import photos

    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])

    presign = client.post(
        f"/api/v1/jobs/{parties['job'].id}/photos/presign",
        headers=headers,
        json={"mime_type": "image/png", "file_size": 1024},
    )
    assert presign.status_code == 200, presign.text
    storage_key = presign.json()["data"]["storage_key"]

    # Finalize without ever uploading: head() finds nothing.
    monkeypatch.setattr(photos.get_object_storage(), "head", lambda key: None)
    response = client.post(
        f"/api/v1/jobs/{parties['job'].id}/photos",
        headers=headers,
        json={"storage_key": storage_key, "photo_type": "BEFORE"},
    )

    assert response.status_code in (400, 404, 422)
    assert_safe(response.text)
    assert db.query(JobPhoto).count() == 0


# ------------------------------------------------------------ the worker


def confirm_a_booking(
    client: TestClient, db: Session, organization: Organization
) -> dict[str, Any]:
    """A confirmed booking, which is the point at which the customer is emailed."""
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["vehicle"], setup["service"])

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )
    assert response.status_code == 200, response.text
    return {"booking": booking, "response": response, **setup}


def test_a_confirmation_commits_even_when_the_queue_will_not_take_the_task(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broker outage must not cost the customer their confirmed appointment.

    The email is staged inside the transaction and dispatched after it commits,
    so a queue that refuses the task leaves a PENDING row for the sweep - not a
    failed request and not a booking that silently did not happen.
    """
    from serviceflow.worker import tasks

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("Error 61 connecting to 127.0.0.1:6380. Connection refused.")

    monkeypatch.setattr(tasks.dispatch_email, "delay", refuse)
    parties = confirm_a_booking(client, db, organization)

    assert_safe(parties["response"].text)
    assert "6380" not in parties["response"].text
    db.expire_all()
    assert db.get(Booking, parties["booking"].id).status is BookingStatus.CONFIRMED

    # The intent survives, ready for the sweep once the broker is back.
    waiting = [row for row in db.query(Notification).all() if row.channel.value == "EMAIL"]
    assert waiting, "the email must still be recorded as pending"
    assert all(row.status.value == "PENDING" for row in waiting)


def test_the_sweep_finds_what_the_outage_missed(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery: once the broker is healthy again, nothing is left stranded."""
    from serviceflow.services import delivery
    from serviceflow.worker import tasks

    # The outage: the task is never queued, so only the sweep can save it.
    monkeypatch.setattr(tasks.dispatch_email, "delay", lambda *a, **k: None)
    confirm_a_booking(client, db, organization)
    monkeypatch.undo()

    # The sweep ignores fresh rows so it cannot race a dispatch still in
    # flight; age them past that grace period.
    db.execute(
        Notification.__table__.update().values(
            created_at=Notification.__table__.c.created_at - text("interval '1 day'")
        )
    )
    db.commit()

    stranded = delivery.stranded_pending_ids(db)
    assert stranded, "the sweep must find the message the outage missed"


# --------------------------------------------------- preconditions that change


def test_an_employee_deactivated_before_confirmation_cannot_be_assigned(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["vehicle"], setup["service"])

    deactivated = client.patch(
        f"/api/v1/employees/{setup['employee'].id}", headers=headers, json={"active": False}
    )
    assert deactivated.status_code == 200, deactivated.text

    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "deactivated" in response.text
    assert_safe(response.text)
    db.expire_all()
    assert db.get(Booking, booking.id).status is BookingStatus.PENDING


def test_a_deactivated_employee_loses_access_to_their_own_jobs(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Lost authorization mid-session: the token still parses, access does not."""
    admin = make_user(db, organization, role=Role.ADMIN)
    parties = job_with_parties(db, organization)
    employee_headers = auth_headers(client, parties["employee_user"])

    assert client.get("/api/v1/jobs", headers=employee_headers).status_code == 200

    client.patch(
        f"/api/v1/employees/{parties['employee'].id}",
        headers=auth_headers(client, admin),
        json={"active": False},
    )

    after = client.get("/api/v1/jobs", headers=employee_headers)
    assert after.status_code in (401, 403)
    assert_safe(after.text)


def test_a_deactivated_service_cannot_be_booked_but_its_history_survives(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    customer_headers = auth_headers(client, setup["customer_user"])

    existing = client.post(
        "/api/v1/bookings",
        headers=customer_headers,
        json={
            "vehicle_id": str(setup["vehicle"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert existing.status_code == 201, existing.text

    retired = client.delete(
        f"/api/v1/services/{setup['service'].id}", headers=auth_headers(client, admin)
    )
    assert retired.status_code == 200, retired.text

    refused = client.post(
        "/api/v1/bookings",
        headers=customer_headers,
        json={
            "vehicle_id": str(setup["vehicle"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start(days=6).isoformat(),
        },
    )
    assert refused.status_code == 422
    assert_safe(refused.text)

    # The booking made while it was live is untouched, and still names the service.
    detail = client.get(
        f"/api/v1/bookings/{existing.json()['data']['id']}", headers=customer_headers
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["service"]["name"] == setup["service"].name


def test_a_booking_that_fails_mid_transaction_leaves_nothing_behind(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transaction failure must roll back the booking and its notification."""
    from serviceflow.services import bookings as bookings_service

    setup = booking_setup(db, organization)

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("connection to server was lost")

    monkeypatch.setattr(bookings_service.notifications, "booking_created", explode)

    headers = auth_headers(client, setup["customer_user"])
    with lenient_client() as strict:
        response = strict.post(
            "/api/v1/bookings",
            headers=headers,
            json={
                "vehicle_id": str(setup["vehicle"].id),
                "service_id": str(setup["service"].id),
                "requested_start": future_start().isoformat(),
            },
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert_safe(response.text)
    assert "connection to server was lost" not in response.text
    assert db.query(Booking).count() == 0
    assert db.query(Notification).count() == 0


def test_a_saturated_connection_pool_asks_the_caller_to_come_back(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running out of connections is congestion, not a defect.

    Load testing at 100 concurrent users exhausted the pool, and every waiting
    caller was told "something went wrong on our end" - which invites a retry
    storm against a queue that is already too long. It now says the server is
    busy and when to come back.
    """
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from serviceflow.services import customers as customers_service

    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    def exhausted(*args: Any, **kwargs: Any) -> None:
        raise PoolTimeout(
            "QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00"
        )

    monkeypatch.setattr(customers_service, "list_customers", exhausted)

    with lenient_client() as strict:
        response = strict.get("/api/v1/customers", headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.headers["Retry-After"] == "5"
    assert_safe(response.text)
    # The pool's shape is an operational detail, not something a caller is told.
    assert "QueuePool" not in response.text
    assert "overflow" not in response.text


def test_a_database_that_refuses_connections_reads_as_congestion(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PostgreSQL's "too many clients" is capacity, not a fault in this request.

    Load testing at 500 concurrent users hit the server's max_connections and
    every refused connection surfaced as a 500. It is a 503 now, so a client
    backs off instead of retrying immediately into a full database.
    """
    from sqlalchemy.exc import OperationalError

    from serviceflow.services import customers as customers_service

    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    def refused(*args: Any, **kwargs: Any) -> None:
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("connection failed: FATAL:  sorry, too many clients already"),
        )

    monkeypatch.setattr(customers_service, "list_customers", refused)

    with lenient_client() as strict:
        response = strict.get("/api/v1/customers", headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.headers["Retry-After"] == "5"
    assert_safe(response.text)
    for leak in ("too many clients", "FATAL", "SELECT 1", "5433"):
        assert leak not in response.text, leak


def test_a_database_error_that_is_not_congestion_is_still_an_error(
    client: TestClient, db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 503 mapping is narrow: a real failure must not hide behind it."""
    from sqlalchemy.exc import OperationalError

    from serviceflow.services import customers as customers_service

    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("deadlock detected"))

    monkeypatch.setattr(customers_service, "list_customers", broken)

    with lenient_client() as strict:
        response = strict.get("/api/v1/customers", headers=headers)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert_safe(response.text)
    assert "deadlock" not in response.text


def test_an_unknown_resource_and_a_foreign_one_read_identically(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Lost authorization must not become an enumeration oracle."""
    setup = booking_setup(db, organization)
    other = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    theirs = make_booking(db, organization, other["customer"], other["vehicle"], other["service"])
    foreign = client.get(f"/api/v1/bookings/{theirs.id}", headers=headers)
    missing = client.get(f"/api/v1/bookings/{uuid.uuid4()}", headers=headers)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


# ------------------------------------------------------- the deployment edge


def test_the_api_refuses_requests_that_did_not_come_through_the_proxy(
    db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In production the API is private to the frontend that sits in front of it.

    That is what makes the forwarded client address believable: a request with a
    hand-written X-Forwarded-For cannot reach the application at all.
    """
    from serviceflow.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "api_proxy_token", "a-shared-secret", raising=False)

    with TestClient(create_app()) as client:
        # Liveness and readiness stay open so probes need no credential.
        assert client.get("/health").status_code == 200

        refused = client.get("/api/v1/customers")
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "FORBIDDEN"
        assert_safe(refused.text)
        # It says nothing about a token existing.
        assert "token" not in refused.text.lower()
        assert "proxy" not in refused.text.lower()

        # With the secret it is an ordinary request again - unauthenticated,
        # because no session was presented.
        allowed = client.get("/api/v1/customers", headers={"X-Proxy-Token": "a-shared-secret"})
        assert allowed.status_code == 401


def test_a_wrong_proxy_token_is_refused(
    db: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch
) -> None:
    from serviceflow.core.config import get_settings

    monkeypatch.setattr(get_settings(), "api_proxy_token", "a-shared-secret", raising=False)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/customers", headers={"X-Proxy-Token": "wrong"})
        assert response.status_code == 403
