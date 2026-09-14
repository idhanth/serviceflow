"""In-app notifications: the events that raise them, and who can read them."""

from __future__ import annotations

import datetime as dt

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
from serviceflow.services.scheduling import (
    AssignmentRequest,
    get_scheduling_policy,
    set_scheduling_policy,
)
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_booking,
    make_organization,
    make_user,
)


def kinds_for(db: Session, user_id) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        row.type.value
        for row in db.query(Notification)
        .filter_by(user_id=user_id)
        .order_by(Notification.created_at)
    ]


def _pending(db: Session, organization: Organization, setup: dict):  # type: ignore[no-untyped-def]
    return make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=4),
    )


# ------------------------------------------------------------------ events


def test_creating_a_booking_notifies_the_admin_and_the_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 201

    assert kinds_for(db, admin.id) == ["BOOKING_CREATED"]
    assert kinds_for(db, setup["customer_user"].id) == ["BOOKING_CREATED"]


def test_confirming_notifies_the_customer_with_the_technician(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)

    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )

    rows = (
        db.query(Notification)
        .filter_by(user_id=setup["customer_user"].id, type=NotificationType.BOOKING_CONFIRMED)
        .all()
    )
    # A customer-facing event lands on both channels: in-app for the badge,
    # email for the outbox the worker drains.
    assert {row.channel for row in rows} == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
    }
    for row in rows:
        assert setup["employee"].user.full_name in row.body
        assert row.payload["booking_id"] == str(booking.id)
        assert row.status is NotificationStatus.PENDING


def test_rejecting_notifies_the_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)

    client.post(
        f"/api/v1/bookings/{booking.id}/reject", headers=auth_headers(client, admin), json={}
    )
    assert "BOOKING_REJECTED" in kinds_for(db, setup["customer_user"].id)


def test_rescheduling_notifies_the_customer_and_the_technician(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)
    headers = auth_headers(client, admin)
    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )

    client.post(
        f"/api/v1/bookings/{booking.id}/reschedule",
        headers=headers,
        json={"requested_start": future_start(days=9).isoformat()},
    )

    assert "BOOKING_RESCHEDULED" in kinds_for(db, setup["customer_user"].id)
    assert "BOOKING_RESCHEDULED" in kinds_for(db, setup["employee_user"].id)


def test_an_admin_cancellation_notifies_the_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)

    client.post(
        f"/api/v1/bookings/{booking.id}/cancel", headers=auth_headers(client, admin), json={}
    )
    assert "BOOKING_CANCELLED" in kinds_for(db, setup["customer_user"].id)


def test_a_customer_cancellation_notifies_the_admin_instead(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Whoever did not do the cancelling is the one who needs telling."""
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)

    client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers=auth_headers(client, setup["customer_user"]),
        json={},
    )

    assert "BOOKING_CANCELLED" in kinds_for(db, admin.id)
    assert "BOOKING_CANCELLED" not in kinds_for(db, setup["customer_user"].id)


def test_starting_and_completing_a_job_notify_the_customer(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])

    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(f"/api/v1/jobs/{parties['job'].id}/complete", headers=staff, json={})

    kinds = kinds_for(db, parties["customer_user"].id)
    assert "JOB_STARTED" in kinds
    assert "JOB_COMPLETED" in kinds

    completed = (
        db.query(Notification)
        .filter_by(
            user_id=parties["customer_user"].id,
            type=NotificationType.JOB_COMPLETED,
            channel=NotificationChannel.IN_APP,
        )
        .one()
    )
    assert parties["service"].name in completed.subject
    assert "photos and notes" in completed.body
    # ...and an email row exists alongside it for the worker.
    assert (
        db.query(Notification)
        .filter_by(
            user_id=parties["customer_user"].id,
            type=NotificationType.JOB_COMPLETED,
            channel=NotificationChannel.EMAIL,
        )
        .count()
        == 1
    )


def test_a_failed_confirmation_leaves_no_notification(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """The strongest property: a rolled-back event tells nobody it happened."""

    class ExplodingPolicy:
        def check_assignment(self, session, request: AssignmentRequest) -> None:  # type: ignore[no-untyped-def]
            raise DependencyUnavailable("Scheduling is unavailable.")

    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    booking = _pending(db, organization, setup)
    before = db.query(Notification).count()

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
    assert db.query(Notification).count() == before
    assert db.query(Notification).filter_by(type=NotificationType.BOOKING_CONFIRMED).count() == 0


def test_a_rejected_booking_creation_leaves_no_notification(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422
    assert db.query(Notification).count() == 0


# ------------------------------------------------------------------ reading


def test_a_user_sees_only_their_own_notifications(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )

    customer_rows = client.get(
        "/api/v1/notifications", headers=auth_headers(client, setup["customer_user"])
    ).json()
    admin_rows = client.get("/api/v1/notifications", headers=auth_headers(client, admin)).json()

    assert customer_rows["meta"]["total"] == 1
    assert admin_rows["meta"]["total"] == 1
    assert customer_rows["data"][0]["id"] != admin_rows["data"][0]["id"]
    assert "received your booking" in customer_rows["data"][0]["subject"]
    assert "New booking request" in admin_rows["data"][0]["subject"]


def test_notifications_are_isolated_across_organizations(
    client: TestClient, db: Session, organization: Organization
) -> None:
    rival = make_organization(db, name="Rival Detailing")
    rival_parties = job_with_parties(db, rival)
    client.post(
        f"/api/v1/jobs/{rival_parties['job'].id}/start",
        headers=auth_headers(client, rival_parties["employee_user"], rival),
    )
    assert db.query(Notification).count() == 1

    parties = job_with_parties(db, organization)
    ours = client.get(
        "/api/v1/notifications", headers=auth_headers(client, parties["customer_user"])
    ).json()
    assert ours["meta"]["total"] == 0


def test_unread_count_and_marking_one_read(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(f"/api/v1/jobs/{parties['job'].id}/complete", headers=staff, json={})
    customer = auth_headers(client, parties["customer_user"])

    assert (
        client.get("/api/v1/notifications/unread-count", headers=customer).json()["data"]["unread"]
        == 2
    )

    first = client.get("/api/v1/notifications", headers=customer).json()["data"][0]
    read = client.post(f"/api/v1/notifications/{first['id']}/read", headers=customer)
    assert read.status_code == 200
    assert read.json()["data"]["unread"] is False
    assert (
        client.get("/api/v1/notifications/unread-count", headers=customer).json()["data"]["unread"]
        == 1
    )

    unread_only = client.get("/api/v1/notifications?unread_only=true", headers=customer).json()
    assert unread_only["meta"]["total"] == 1


def test_marking_all_read(client: TestClient, db: Session, organization: Organization) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])
    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(f"/api/v1/jobs/{parties['job'].id}/complete", headers=staff, json={})
    customer = auth_headers(client, parties["customer_user"])

    result = client.post("/api/v1/notifications/read-all", headers=customer)
    assert result.status_code == 200
    assert result.json()["data"]["marked"] == 2
    assert (
        client.get("/api/v1/notifications/unread-count", headers=customer).json()["data"]["unread"]
        == 0
    )

    # Idempotent: a second call marks nothing.
    assert (
        client.post("/api/v1/notifications/read-all", headers=customer).json()["data"]["marked"]
        == 0
    )


def test_another_users_notification_cannot_be_marked_read(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    admin_notification = db.query(Notification).filter_by(user_id=admin.id).one()

    response = client.post(
        f"/api/v1/notifications/{admin_notification.id}/read",
        headers=auth_headers(client, setup["customer_user"]),
    )
    assert response.status_code == 404
    db.refresh(admin_notification)
    assert admin_notification.status is NotificationStatus.PENDING


def test_notifications_read_newest_first_and_paginate(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    for offset in range(3):
        make_booking(
            db,
            organization,
            setup["customer"],
            setup["service"],
            start=future_start(days=5 + offset),
        )
        client.post(
            "/api/v1/bookings",
            headers=auth_headers(client, setup["customer_user"]),
            json={
                "service_id": str(setup["service"].id),
                "requested_start": future_start(days=11 + offset).isoformat(),
            },
        )
    headers = auth_headers(client, admin)

    page = client.get("/api/v1/notifications?page=1&page_size=2", headers=headers).json()
    assert page["meta"] == {"page": 1, "page_size": 2, "total": 3, "pages": 2}
    stamps = [row["created_at"] for row in page["data"]]
    assert stamps == sorted(stamps, reverse=True)


def test_signed_out_callers_get_nothing(client: TestClient) -> None:
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.get("/api/v1/notifications/unread-count").status_code == 401
