"""Booking creation and the customer/admin access boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.db.models.organization import Organization
from serviceflow.services.bookings import booking_window
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    make_booking,
    make_customer,
    make_service,
    make_user,
)


def test_end_time_is_derived_from_the_service_duration(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """PRD 8: a 150 minute service booked at 10:00 ends at 12:30."""
    setup = booking_setup(db, organization)
    start = future_start(hour=10)

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": start.isoformat(),
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]

    requested_start = datetime.fromisoformat(data["requested_start"])
    requested_end = datetime.fromisoformat(data["requested_end"])
    assert requested_end - requested_start == timedelta(minutes=150)
    assert data["status"] == "PENDING"


def test_a_client_supplied_end_time_is_ignored(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Trusting a client end time would let a 150 minute job book a 5 minute slot."""
    setup = booking_setup(db, organization)
    start = future_start(hour=9)

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": start.isoformat(),
            "requested_end": (start + timedelta(minutes=5)).isoformat(),
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    span = datetime.fromisoformat(data["requested_end"]) - datetime.fromisoformat(
        data["requested_start"]
    )
    assert span == timedelta(minutes=150)


def test_booking_window_helper_is_timezone_correct(db: Session, organization: Organization) -> None:
    service = make_service(db, organization, duration_minutes=90)
    # 09:00 in a UTC+2 zone is 07:00 UTC; the window must be stored in UTC.
    start = datetime(2027, 3, 1, 9, 0, tzinfo=timezone_plus_two())
    window_start, window_end = booking_window(service, start)
    assert window_start.tzinfo == UTC
    assert window_start.hour == 7
    assert window_end - window_start == timedelta(minutes=90)


def timezone_plus_two():
    from datetime import timezone

    return timezone(timedelta(hours=2))


def test_customer_books_for_themselves(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
            "customer_notes": "Please focus on the wheels.",
        },
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["customer_notes"] == "Please focus on the wheels."
    # Admin-only fields stay hidden from the customer.
    assert data["customer"] is None
    assert data["admin_notes"] is None


def test_customer_cannot_book_on_behalf_of_someone_else(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    stranger = make_customer(db, organization, email="stranger@example.com")

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "customer_id": str(stranger.id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 403


def test_a_retired_service_cannot_be_booked(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    setup["service"].active = False
    db.commit()

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["service_id"]


def test_an_archived_customer_cannot_be_booked(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    owner = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, owner)
    assert (
        client.delete(f"/api/v1/customers/{setup['customer'].id}", headers=headers).status_code
        == 200
    )

    response = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "customer_id": str(setup["customer"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["customer_id"]


def test_a_time_in_the_past_is_refused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, setup["customer_user"]),
        json={
            "service_id": str(setup["service"].id),
            "requested_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["requested_start"]


def test_customer_cannot_read_another_customers_booking(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    stranger = make_customer(db, organization, email="stranger@example.com")
    theirs = make_booking(db, organization, stranger, setup["service"])
    headers = auth_headers(client, setup["customer_user"])

    assert client.get(f"/api/v1/bookings/{theirs.id}", headers=headers).status_code == 404
    assert (
        client.post(f"/api/v1/bookings/{theirs.id}/cancel", headers=headers, json={}).status_code
        == 404
    )
    listing = client.get("/api/v1/bookings", headers=headers).json()
    assert listing["meta"]["total"] == 0


def test_customer_cannot_filter_the_list_to_someone_else(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    stranger = make_customer(db, organization, email="stranger@example.com")
    response = client.get(
        f"/api/v1/bookings?customer_id={stranger.id}",
        headers=auth_headers(client, setup["customer_user"]),
    )
    assert response.status_code == 403


def test_customer_cancels_their_own_pending_booking(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    response = client.post(
        f"/api/v1/bookings/{booking.id}/cancel",
        headers=auth_headers(client, setup["customer_user"]),
        json={},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


def test_customers_cannot_confirm_or_reject(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, setup["customer_user"])

    assert (
        client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=headers,
            json={"employee_id": str(setup["employee"].id)},
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/bookings/{booking.id}/reject", headers=headers, json={}).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/bookings/{booking.id}/assignable-employees", headers=headers
        ).status_code
        == 403
    )


def test_admin_sees_internal_fields_and_all_bookings(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    make_booking(db, organization, setup["customer"], setup["service"])

    listing = client.get("/api/v1/bookings", headers=auth_headers(client, admin)).json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["customer"]["full_name"] == "Booker Customer"


def test_timeframe_and_status_filters(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    make_booking(db, organization, setup["customer"], setup["service"])
    make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=datetime.now(UTC) - timedelta(days=5),
        status=BookingStatus.CONFIRMED,
    )
    headers = auth_headers(client, admin)

    assert (
        client.get("/api/v1/bookings?timeframe=upcoming", headers=headers).json()["meta"]["total"]
        == 1
    )
    assert (
        client.get("/api/v1/bookings?timeframe=past", headers=headers).json()["meta"]["total"] == 1
    )
    assert (
        client.get("/api/v1/bookings?status=PENDING", headers=headers).json()["meta"]["total"] == 1
    )


def test_employees_have_no_booking_access(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """PRD 6 gives employees jobs, not bookings - and the refusal should say so."""
    setup = booking_setup(db, organization)
    booking = make_booking(db, organization, setup["customer"], setup["service"])
    headers = auth_headers(client, setup["employee_user"])

    listing = client.get("/api/v1/bookings", headers=headers)
    assert listing.status_code == 403
    assert listing.json()["error"]["code"] == "INVALID_ROLE"

    detail = client.get(f"/api/v1/bookings/{booking.id}", headers=headers)
    assert detail.status_code == 403

    assert (
        client.post(f"/api/v1/bookings/{booking.id}/cancel", headers=headers, json={}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/bookings",
            headers=headers,
            json={
                "service_id": str(setup["service"].id),
                "requested_start": future_start().isoformat(),
            },
        ).status_code
        == 403
    )


def test_a_job_finished_early_moves_the_booking_into_history(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A completed job is history even if its slot is still in the future.

    Without this the booking would sit under "Upcoming" with a finished job and
    never appear in the customer's past visits.
    """
    from serviceflow.db.models.enums import JobStatus
    from tests.conftest import make_job

    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=5),
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, booking, setup["employee"], status=JobStatus.COMPLETED)
    headers = auth_headers(client, setup["customer_user"])

    upcoming = client.get("/api/v1/bookings?timeframe=upcoming", headers=headers).json()
    past = client.get("/api/v1/bookings?timeframe=past", headers=headers).json()

    assert upcoming["meta"]["total"] == 0
    assert [row["id"] for row in past["data"]] == [str(booking.id)]


def test_upcoming_and_past_partition_every_booking(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """No booking may be missing from both tabs, or present in both."""
    from serviceflow.db.models.enums import JobStatus
    from tests.conftest import make_job

    setup = booking_setup(db, organization)
    made: list[str] = []

    # One of every meaningful shape.
    pending = make_booking(db, organization, setup["customer"], setup["service"])
    made.append(str(pending.id))
    made.append(
        str(
            make_booking(
                db,
                organization,
                setup["customer"],
                setup["service"],
                start=datetime.now(UTC) - timedelta(days=3),
                status=BookingStatus.CONFIRMED,
            ).id
        )
    )
    made.append(
        str(
            make_booking(
                db,
                organization,
                setup["customer"],
                setup["service"],
                status=BookingStatus.REJECTED,
            ).id
        )
    )
    made.append(
        str(
            make_booking(
                db,
                organization,
                setup["customer"],
                setup["service"],
                status=BookingStatus.CANCELLED,
            ).id
        )
    )
    finished = make_booking(
        db,
        organization,
        setup["customer"],
        setup["service"],
        start=future_start(days=6),
        status=BookingStatus.CONFIRMED,
    )
    make_job(db, organization, finished, setup["employee"], status=JobStatus.COMPLETED)
    made.append(str(finished.id))

    headers = auth_headers(client, setup["customer_user"])
    upcoming = {
        row["id"]
        for row in client.get(
            "/api/v1/bookings?timeframe=upcoming&page_size=50", headers=headers
        ).json()["data"]
    }
    past = {
        row["id"]
        for row in client.get(
            "/api/v1/bookings?timeframe=past&page_size=50", headers=headers
        ).json()["data"]
    }

    assert upcoming & past == set(), "a booking appeared in both timeframes"
    assert upcoming | past == set(made), "a booking was missing from both timeframes"
