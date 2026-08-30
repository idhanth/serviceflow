"""Appointment reminders: the window, and never sending one twice."""

from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import (
    BookingStatus,
    JobStatus,
    NotificationChannel,
    NotificationType,
)
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.db.session import get_session_factory
from serviceflow.services import reminders
from tests.conftest import booking_setup, make_booking, make_job

LEAD_HOURS = 24
WINDOW_MINUTES = 90


def run(db: Session, *, now: dt.datetime | None = None) -> int:
    return reminders.create_due_reminders(
        db, lead_hours=LEAD_HOURS, window_minutes=WINDOW_MINUTES, now=now
    )


def reminder_rows(db: Session) -> list[Notification]:
    return (
        db.query(Notification)
        .filter_by(type=NotificationType.APPOINTMENT_REMINDER)
        .order_by(Notification.created_at)
        .all()
    )


def _confirmed_at(
    db: Session,
    organization: Organization,
    setup: dict,
    start: dt.datetime,
    *,
    status=JobStatus.ASSIGNED,
):  # type: ignore[no-untyped-def]
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=start,
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, booking, setup["employee"], status=status)
    return booking


def test_an_upcoming_confirmed_booking_gets_one_reminder(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    start = dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS)
    booking = _confirmed_at(db, organization, setup, start)

    assert run(db) == 1

    rows = reminder_rows(db)
    # In-app for the badge, email for the outbox.
    assert {row.channel for row in rows} == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
    }
    assert all(row.payload["booking_id"] == str(booking.id) for row in rows)
    assert all(row.user_id == setup["customer_user"].id for row in rows)


def test_a_second_tick_creates_nothing(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    _confirmed_at(db, organization, setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS))

    assert run(db) == 1
    assert run(db) == 0
    assert run(db) == 0
    assert len(reminder_rows(db)) == 2  # the same two channel rows, not six


def test_bookings_outside_the_window_are_left_alone(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    now = dt.datetime.now(dt.UTC)
    # Too far out, and too close in.
    _confirmed_at(db, organization, setup, now + dt.timedelta(hours=LEAD_HOURS + 6))
    _confirmed_at(db, organization, setup, now + dt.timedelta(hours=2))

    assert run(db) == 0


def test_the_window_edges_are_inclusive(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    now = dt.datetime.now(dt.UTC)
    _confirmed_at(
        db,
        organization,
        setup,
        now + dt.timedelta(hours=LEAD_HOURS, minutes=-WINDOW_MINUTES + 1),
    )
    _confirmed_at(
        db,
        organization,
        setup,
        now + dt.timedelta(hours=LEAD_HOURS, minutes=WINDOW_MINUTES - 1),
    )

    assert run(db) == 2


def test_a_cancelled_booking_is_not_reminded(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    booking = _confirmed_at(
        db, organization, setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS)
    )
    booking.status = BookingStatus.CANCELLED
    db.commit()

    assert run(db) == 0


def test_a_rejected_booking_is_not_reminded(db: Session, organization: Organization) -> None:
    setup = booking_setup(db, organization)
    make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS),
        status=BookingStatus.REJECTED,
    )
    assert run(db) == 0


def test_a_pending_booking_is_not_reminded(db: Session, organization: Organization) -> None:
    """Nothing is confirmed yet, so there is nothing to remind anyone about."""
    setup = booking_setup(db, organization)
    make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        start=dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS),
    )
    assert run(db) == 0


def test_a_completed_or_cancelled_job_is_not_reminded(
    db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    now = dt.datetime.now(dt.UTC)
    _confirmed_at(
        db, organization, setup, now + dt.timedelta(hours=LEAD_HOURS), status=JobStatus.COMPLETED
    )
    _confirmed_at(
        db, organization, setup, now + dt.timedelta(hours=LEAD_HOURS), status=JobStatus.CANCELLED
    )
    assert run(db) == 0


def test_an_appointment_already_in_the_past_is_not_reminded(
    db: Session, organization: Organization
) -> None:
    """Yesterday's appointment must never be reminded about, at any tick."""
    setup = booking_setup(db, organization)
    now = dt.datetime.now(dt.UTC)
    _confirmed_at(db, organization, setup, now - dt.timedelta(hours=2))
    _confirmed_at(db, organization, setup, now - dt.timedelta(hours=LEAD_HOURS))
    _confirmed_at(db, organization, setup, now - dt.timedelta(days=3))

    assert run(db) == 0
    assert reminder_rows(db) == []


def test_the_reminder_reads_in_the_organizations_timezone(
    db: Session, organization: Organization
) -> None:
    """The body quotes the shop's local time, not UTC."""
    organization.timezone = "America/Los_Angeles"
    db.commit()
    setup = booking_setup(db, organization)

    # 20:00 UTC is 13:00 in Los Angeles during PDT.
    start = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    _confirmed_at(db, organization, setup, start)
    run(db, now=start - dt.timedelta(hours=LEAD_HOURS))

    rows = reminder_rows(db)
    assert rows, "expected a reminder"
    assert "1:00pm" in rows[0].subject or "1:00pm" in rows[0].body


def test_reminders_do_not_cross_organizations(db: Session, organization: Organization) -> None:
    from tests.conftest import make_organization

    rival = make_organization(db, name="Rival Detailing")
    rival_setup = booking_setup(db, rival)
    _confirmed_at(db, rival, rival_setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS))

    assert run(db) == 1
    rows = reminder_rows(db)
    assert all(row.organization_id == rival.id for row in rows)


def test_concurrent_scheduler_runs_do_not_duplicate(
    db: Session, organization: Organization
) -> None:
    """Two beats firing at once must still produce one reminder.

    Real threads and real sessions, so the advisory lock is genuinely exercised.
    """
    setup = booking_setup(db, organization)
    _confirmed_at(db, organization, setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS))

    barrier = threading.Barrier(4)
    factory = get_session_factory()

    def tick() -> int:
        session = factory()
        try:
            barrier.wait(timeout=10)
            return reminders.create_due_reminders(
                session, lead_hours=LEAD_HOURS, window_minutes=WINDOW_MINUTES
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(tick) for _ in range(4)]]

    assert sum(results) == 1, f"exactly one run should have created it, got {results}"
    db.expire_all()
    assert len(reminder_rows(db)) == 2  # one in-app, one email


def test_the_worker_task_creates_reminders(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from serviceflow.worker import tasks

    setup = booking_setup(db, organization)
    _confirmed_at(db, organization, setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS))

    assert tasks.queue_appointment_reminders() == 1
    db.expire_all()
    assert len(reminder_rows(db)) == 2


def test_a_reminder_email_is_deliverable(
    client: TestClient, db: Session, organization: Organization, mailbox: None
) -> None:
    from serviceflow.worker import tasks
    from tests.conftest import mailpit_messages

    setup = booking_setup(db, organization)
    _confirmed_at(db, organization, setup, dt.datetime.now(dt.UTC) + dt.timedelta(hours=LEAD_HOURS))
    run(db)

    email = next(r for r in reminder_rows(db) if r.channel is NotificationChannel.EMAIL)
    assert tasks.dispatch_email(str(email.id)) == "sent"
    assert any("Reminder" in m["Subject"] for m in mailpit_messages())
