"""Booking idempotency (PRD 14), including the concurrent duplicate race.

The concurrency cases run real threads against real PostgreSQL: the guarantee is
a unique constraint, and a test that mocked the database would prove nothing
about it.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import Role
from serviceflow.db.models.idempotency import IdempotencyRecord
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.services import idempotency
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    make_organization,
    make_user,
)

KEY = "booking-attempt-01HZY7Q2"


def body(setup: dict, **overrides) -> dict:  # type: ignore[no-untyped-def]
    payload = {
        "service_id": str(setup["service"].id),
        "requested_start": future_start().isoformat(),
    }
    payload.update(overrides)
    return payload


def post(client: TestClient, headers: dict, payload: dict, key: str | None = KEY):  # type: ignore[no-untyped-def]
    request_headers = dict(headers)
    if key is not None:
        request_headers["Idempotency-Key"] = key
    return client.post("/api/v1/bookings", headers=request_headers, json=payload)


# ------------------------------------------------------------------ basics


def test_a_first_keyed_request_creates_the_booking(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    response = post(client, auth_headers(client, setup["customer_user"]), body(setup))

    assert response.status_code == 201
    assert response.headers.get("Idempotent-Replay") is None
    assert db.query(Booking).count() == 1
    record = db.query(IdempotencyRecord).one()
    assert record.completed
    assert record.resource_id == uuid.UUID(response.json()["data"]["id"])


def test_a_retry_with_the_same_payload_replays_the_original(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payload = body(setup)

    first = post(client, headers, payload)
    second = post(client, headers, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert db.query(Booking).count() == 1


def test_a_replay_does_not_repeat_side_effects(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A retry must not notify the customer twice or double the audit trail."""
    make_user(db, organization, role=Role.OWNER)
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payload = body(setup)

    post(client, headers, payload)
    notifications_after_first = db.query(Notification).count()
    audits_after_first = db.query(AuditLog).count()

    post(client, headers, payload)

    db.expire_all()
    assert db.query(Notification).count() == notifications_after_first
    assert db.query(AuditLog).count() == audits_after_first
    assert db.query(Booking).count() == 1


def test_the_same_key_with_a_different_payload_conflicts(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    assert post(client, headers, body(setup)).status_code == 201
    changed = post(client, headers, body(setup, requested_start=future_start(days=9).isoformat()))

    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert db.query(Booking).count() == 1


def test_a_request_without_a_key_is_unaffected(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    assert post(client, headers, body(setup), key=None).status_code == 201
    # Without a key there is nothing to replay, but an identical second booking
    # is still refused - by the database's no-duplicate index, not by the key.
    again = post(client, headers, body(setup), key=None)
    assert again.status_code == 409
    assert again.json()["error"]["details"]["reason"] == "DUPLICATE_BOOKING"
    assert db.query(Booking).count() == 1
    assert db.query(IdempotencyRecord).count() == 0


# ------------------------------------------------------------------ scoping


def test_two_users_may_use_the_same_key_independently(
    client: TestClient, db: Session, organization: Organization
) -> None:
    first = booking_setup(db, organization)
    second = booking_setup(db, organization)

    a = post(client, auth_headers(client, first["customer_user"]), body(first))
    b = post(client, auth_headers(client, second["customer_user"]), body(second))

    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["data"]["id"] != b.json()["data"]["id"]
    assert db.query(Booking).count() == 2


def test_two_organizations_may_use_the_same_key_independently(
    client: TestClient, db: Session, organization: Organization
) -> None:
    ours = booking_setup(db, organization)
    rival = make_organization(db, name="Rival Detailing")
    theirs = booking_setup(db, rival)

    a = post(client, auth_headers(client, ours["customer_user"], organization), body(ours))
    b = post(client, auth_headers(client, theirs["customer_user"], rival), body(theirs))

    assert a.status_code == 201
    assert b.status_code == 201
    assert db.query(Booking).count() == 2
    assert db.query(IdempotencyRecord).count() == 2


# ------------------------------------------------------------------ keys


@pytest.mark.parametrize(
    "key",
    ["short", "", "   ", "has spaces in it", "curly{braces}", "a" * 201, "semi;colon"],
)
def test_a_malformed_key_is_rejected(
    client: TestClient, db: Session, organization: Organization, key: str
) -> None:
    setup = booking_setup(db, organization)
    response = post(client, auth_headers(client, setup["customer_user"]), body(setup), key=key)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert db.query(Booking).count() == 0


def test_an_expired_key_can_be_reused(
    client: TestClient, db: Session, organization: Organization
) -> None:
    import datetime as dt

    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    assert post(client, headers, body(setup)).status_code == 201

    record = db.query(IdempotencyRecord).one()
    record.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    db.commit()

    # A genuinely new request that happens to reuse an old token.
    again = post(client, headers, body(setup, requested_start=future_start(days=11).isoformat()))
    assert again.status_code == 201
    assert db.query(Booking).count() == 2
    assert db.query(IdempotencyRecord).count() == 1


def test_expired_records_are_purged(
    client: TestClient, db: Session, organization: Organization
) -> None:
    import datetime as dt

    setup = booking_setup(db, organization)
    post(client, auth_headers(client, setup["customer_user"]), body(setup))
    record = db.query(IdempotencyRecord).one()
    record.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    db.commit()

    assert idempotency.purge_expired(db) == 1
    assert db.query(IdempotencyRecord).count() == 0
    # The booking it described is untouched.
    assert db.query(Booking).count() == 1


def test_the_purge_is_actually_scheduled() -> None:
    """Retention is only a policy if something enforces it."""
    from serviceflow.worker.celery_app import celery_app

    scheduled = {
        entry["task"]
        for entry in celery_app.conf.beat_schedule.values()  # type: ignore[union-attr]
    }
    assert "serviceflow.purge_expired_idempotency_keys" in scheduled


def test_the_purge_task_deletes_expired_records(
    client: TestClient, db: Session, organization: Organization
) -> None:
    import datetime as dt

    from serviceflow.worker.tasks import purge_expired_idempotency_keys

    setup = booking_setup(db, organization)
    post(client, auth_headers(client, setup["customer_user"]), body(setup))
    record = db.query(IdempotencyRecord).one()
    record.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    db.commit()

    assert purge_expired_idempotency_keys() == 1
    assert db.query(IdempotencyRecord).count() == 0


# ------------------------------------------------------------------ rollback


def test_a_rolled_back_booking_leaves_no_idempotency_record(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """A record must never claim success for work that did not commit."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    # A retired service fails validation after the record has been staged.
    setup["service"].active = False
    db.commit()

    response = post(client, headers, body(setup))
    assert response.status_code == 422

    db.expire_all()
    assert db.query(Booking).count() == 0
    assert db.query(IdempotencyRecord).count() == 0

    # And the key is still usable once the cause is fixed.
    setup["service"].active = True
    db.commit()
    assert post(client, headers, body(setup)).status_code == 201


# ------------------------------------------------------------------ concurrency


def _fire_together(calls: list) -> list:  # type: ignore[type-arg]
    """Release every call from one barrier so the race actually happens."""
    barrier = threading.Barrier(len(calls))

    def run(call):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=15)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=45) for f in [pool.submit(run, c) for c in calls]]


@pytest.mark.concurrency
@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_identical_requests_create_exactly_one_booking(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payload = body(setup)

    responses = _fire_together([(lambda: post(client, headers, payload)) for _ in range(5)])
    codes = Counter(r.status_code for r in responses)

    db.expire_all()
    assert db.query(Booking).count() == 1, f"duplicate bookings created: {codes}"
    assert db.query(IdempotencyRecord).count() == 1

    # Whoever succeeded agrees on which booking it is.
    booking_id = str(db.query(Booking).one().id)
    for response in responses:
        if response.status_code in (200, 201):
            assert response.json()["data"]["id"] == booking_id
        else:
            # A loser that arrived mid-flight is told so, not given a second booking.
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    assert codes[200] + codes[201] >= 1, f"nobody succeeded: {codes}"


@pytest.mark.concurrency
@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_same_key_different_payloads_create_at_most_one_booking(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payloads = [
        body(setup, requested_start=future_start(days=day).isoformat()) for day in (3, 4, 5, 6)
    ]

    responses = _fire_together(
        [(lambda p=p: post(client, headers, p)) for p in payloads]  # type: ignore[misc]
    )
    codes = Counter(r.status_code for r in responses)

    db.expire_all()
    assert db.query(Booking).count() <= 1, f"more than one booking created: {codes}"
    assert codes[409] >= 1, f"incompatible requests should conflict: {codes}"
    for response in responses:
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.concurrency
@pytest.mark.parametrize("attempt", range(2))
def test_concurrent_different_keys_all_succeed(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Idempotency must not serialise unrelated requests into failures."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    calls = [
        (
            lambda day=day: post(
                client,
                headers,
                body(setup, requested_start=future_start(days=day).isoformat()),
                key=f"distinct-key-{day:03d}",
            )
        )
        for day in (3, 5, 7, 9)
    ]
    responses = _fire_together(calls)  # type: ignore[arg-type]

    assert all(r.status_code == 201 for r in responses), Counter(r.status_code for r in responses)
    db.expire_all()
    assert db.query(Booking).count() == 4
