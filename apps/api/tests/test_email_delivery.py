"""The email outbox: from business event to SENT, and every way it can fail.

Emails really are delivered here, over SMTP to the local MailPit, and asserted
against its API. Failure paths use a recording provider so a specific error can
be forced, but the success path is genuine delivery.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.core.errors import DependencyUnavailable
from serviceflow.db.models.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    Role,
)
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.services import delivery
from serviceflow.services.scheduling import (
    AssignmentRequest,
    get_scheduling_policy,
    set_scheduling_policy,
)
from serviceflow.worker import tasks
from tests.conftest import (
    RecordingProvider,
    auth_headers,
    booking_setup,
    email_rows,
    future_start,
    job_with_parties,
    mailpit_body,
    mailpit_messages,
    make_booking,
    make_user,
)


def confirm_a_booking(client: TestClient, db: Session, organization: Organization) -> dict:
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=future_start(days=4),
    )
    response = client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )
    assert response.status_code == 200
    return {**setup, "admin": admin, "booking": booking}


# ------------------------------------------------------------------ the outbox


def test_a_confirmation_writes_an_email_row_alongside_the_in_app_one(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = confirm_a_booking(client, db, organization)

    rows = email_rows(db, user_id=parties["customer_user"].id)
    assert [row.type for row in rows] == [NotificationType.BOOKING_CONFIRMED]
    assert rows[0].status is NotificationStatus.PENDING
    assert rows[0].sent_at is None and rows[0].failed_at is None


def test_a_rolled_back_confirmation_writes_no_email(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The phase 5 guarantee, now that an email would be a real side effect."""

    class ExplodingPolicy:
        def check_assignment(self, session, request: AssignmentRequest) -> None:  # type: ignore[no-untyped-def]
            raise DependencyUnavailable("Scheduling is unavailable.")

    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=future_start(days=4),
    )

    previous = get_scheduling_policy()
    set_scheduling_policy(ExplodingPolicy())
    try:
        response = client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=auth_headers(client, admin),
            json={"employee_id": str(setup["employee"].id)},
        )
    finally:
        set_scheduling_policy(previous)

    assert response.status_code == 503
    db.expire_all()
    assert email_rows(db, type=NotificationType.BOOKING_CONFIRMED) == []


def test_the_api_does_not_wait_for_the_email_provider(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """A provider that never answers must not slow or fail the request."""

    class HangingProvider:
        name = "hanging"

        def send(self, message: object) -> str:  # pragma: no cover - never called
            raise AssertionError("the request path must not send email")

    monkeypatch.setattr(delivery, "get_email_provider", lambda: HangingProvider())
    parties = confirm_a_booking(client, db, organization)
    assert email_rows(db, user_id=parties["customer_user"].id)[0].status is (
        NotificationStatus.PENDING
    )


# ------------------------------------------------------------------ the worker


def test_the_worker_sends_a_real_email_and_marks_it_sent(
    client: TestClient, db: Session, organization: Organization, mailbox: None
) -> None:
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    assert tasks.dispatch_email(str(row.id)) == "sent"

    db.expire_all()
    stored = db.get(Notification, row.id)
    assert stored is not None
    assert stored.status is NotificationStatus.SENT
    assert stored.sent_at is not None
    assert stored.failed_at is None

    captured = mailpit_messages()
    assert len(captured) == 1
    assert captured[0]["To"][0]["Address"] == parties["customer_user"].email
    assert organization.name in captured[0]["Subject"]


def test_the_email_body_carries_the_business_details_and_no_internals(
    client: TestClient, db: Session, organization: Organization, mailbox: None
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    client.post(
        f"/api/v1/jobs/{parties['job'].id}/notes",
        headers=staff,
        json={"content": "SECRET-INTERNAL do not tell them", "visibility": "INTERNAL"},
    )
    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(
        f"/api/v1/jobs/{parties['job'].id}/complete",
        headers=staff,
        json={"internal_notes": "SECRET-COMPLETION margin was thin"},
    )

    row = email_rows(db, type=NotificationType.JOB_COMPLETED)[0]
    assert tasks.dispatch_email(str(row.id)) == "sent"

    body = mailpit_body(mailpit_messages()[0]["ID"])
    assert parties["booking"].vehicle.display_name in body
    assert organization.name in body
    assert "SECRET-INTERNAL" not in body
    assert "SECRET-COMPLETION" not in body


def test_dispatching_the_same_row_twice_sends_once(
    client: TestClient, db: Session, organization: Organization, mailbox: None
) -> None:
    """Task redelivery is safe: an already-sent row is a no-op."""
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    assert tasks.dispatch_email(str(row.id)) == "sent"
    assert tasks.dispatch_email(str(row.id)) == "skipped"

    assert len(mailpit_messages()) == 1
    db.expire_all()
    assert (
        db.query(Notification).filter_by(type=NotificationType.BOOKING_CONFIRMED).count() == 2
    )  # one IN_APP, one EMAIL - no duplicates created


def test_a_transient_provider_failure_is_retried(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    provider = RecordingProvider(fail_times=1)
    monkeypatch.setattr(delivery, "get_email_provider", lambda: provider)

    # Run through Celery so the retry machinery has a request context. The first
    # attempt fails, the task asks to be retried, and the retry succeeds.
    result = tasks.dispatch_email.apply(args=[str(row.id)])

    assert result.state == "SUCCESS", result.state
    assert result.result == "sent"
    assert provider.attempts == 2, "the first attempt should have failed and been retried"

    db.expire_all()
    stored = db.get(Notification, row.id)
    assert stored.status is NotificationStatus.SENT
    assert stored.sent_at is not None
    # A retry must not have produced a second row.
    assert len(email_rows(db, id=row.id)) == 1


def test_a_permanent_rejection_fails_the_row_without_retrying(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    provider = RecordingProvider(fail_times=99, permanent=True)
    monkeypatch.setattr(delivery, "get_email_provider", lambda: provider)

    assert tasks.dispatch_email(str(row.id)) == "failed"

    db.expire_all()
    stored = db.get(Notification, row.id)
    assert stored.status is NotificationStatus.FAILED
    assert stored.failed_at is not None
    assert stored.sent_at is None
    assert provider.attempts == 1, "a permanent rejection must not be retried"


def test_exhausted_retries_mark_the_row_failed(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    monkeypatch.setattr(delivery, "get_email_provider", lambda: RecordingProvider(fail_times=99))

    # Standing in for Celery having used up its retry budget.
    from celery.exceptions import MaxRetriesExceededError

    def exhausted(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise MaxRetriesExceededError()

    monkeypatch.setattr(tasks.dispatch_email, "retry", exhausted)

    assert tasks.dispatch_email(str(row.id)) == "failed"
    db.expire_all()
    stored = db.get(Notification, row.id)
    assert stored.status is NotificationStatus.FAILED
    assert stored.failed_at is not None


def test_the_in_app_notification_survives_an_email_failure(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """A dead provider must not cost the customer their in-app notification."""
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]
    monkeypatch.setattr(
        delivery, "get_email_provider", lambda: RecordingProvider(fail_times=99, permanent=True)
    )
    tasks.dispatch_email(str(row.id))

    listing = client.get(
        "/api/v1/notifications", headers=auth_headers(client, parties["customer_user"])
    ).json()
    assert listing["meta"]["total"] >= 1
    assert any(r["type"] == "BOOKING_CONFIRMED" for r in listing["data"])


# ------------------------------------------------------------------ the sweep


def test_the_sweep_finds_rows_that_were_never_dispatched(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """A broker outage right after the commit must not lose the email."""
    parties = confirm_a_booking(client, db, organization)
    row = email_rows(db, user_id=parties["customer_user"].id)[0]

    # Age it past the stranded threshold.
    db.execute(
        Notification.__table__.update()
        .where(Notification.id == row.id)
        .values(created_at=row.created_at.replace(year=row.created_at.year - 1))
    )
    db.commit()

    queued: list[str] = []
    monkeypatch.setattr(
        tasks.dispatch_email, "delay", lambda notification_id: queued.append(notification_id)
    )

    assert tasks.sweep_pending_emails() == 1
    assert queued == [str(row.id)]


def test_the_sweep_ignores_fresh_sent_and_failed_rows(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    confirm_a_booking(client, db, organization)
    queued: list[str] = []
    monkeypatch.setattr(
        tasks.dispatch_email, "delay", lambda notification_id: queued.append(notification_id)
    )

    # Just-created rows are left for their own dispatch.
    assert tasks.sweep_pending_emails() == 0
    assert queued == []


def test_a_cancellation_email_is_queued(
    client: TestClient, db: Session, organization: Organization, mailbox: None
) -> None:
    parties = confirm_a_booking(client, db, organization)
    client.post(
        f"/api/v1/bookings/{parties['booking'].id}/cancel",
        headers=auth_headers(client, parties["admin"]),
        json={},
    )

    rows = email_rows(db, type=NotificationType.BOOKING_CANCELLED)
    assert len(rows) == 1
    assert tasks.dispatch_email(str(rows[0].id)) == "sent"
    assert any("cancelled" in m["Subject"].lower() for m in mailpit_messages())


def test_admin_operational_alerts_stay_in_app_only(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A new booking request notifies admins in-app; it does not email them."""
    admin = make_user(db, organization, role=Role.ADMIN)
    setup = booking_setup(db, organization)
    client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "vehicle_id": str(setup["vehicle"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )

    assert email_rows(db, user_id=admin.id) == []
    assert (
        db.query(Notification)
        .filter_by(user_id=admin.id, channel=NotificationChannel.IN_APP)
        .count()
        == 1
    )
