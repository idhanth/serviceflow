"""Idempotency under sustained concurrency (PRD 14, phase 8).

`test_idempotency.py` proves the semantics and closes the two-request race.
This pushes harder: many callers on one key, many keys at once, and retries that
arrive while the first attempt is still in flight - then checks that the side
effects (audit entries, notifications) were not duplicated either.

Real threads against real PostgreSQL. The unique constraint is the mechanism
being tested, so nothing here may stand in for the database.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.idempotency import IdempotencyRecord
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from tests.conftest import auth_headers, booking_setup, future_start

pytestmark = [pytest.mark.concurrency, pytest.mark.stress]


def fire_together(calls: list[Any], timeout: float = 45.0) -> list[Any]:
    barrier = threading.Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait(timeout=20)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=timeout) for f in [pool.submit(run, c) for c in calls]]


def body(setup: dict[str, Any], days: int = 5) -> dict[str, str]:
    return {
        "vehicle_id": str(setup["vehicle"].id),
        "service_id": str(setup["service"].id),
        "requested_start": future_start(days=days).isoformat(),
    }


def post(client: TestClient, headers: dict[str, str], payload: dict[str, str], key: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/bookings", headers={**headers, "Idempotency-Key": key}, json=payload
    )


@pytest.mark.parametrize("attempt", range(3))
def test_twenty_callers_on_one_key_create_one_booking(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payload = body(setup)
    key = f"stress-single-{uuid.uuid4().hex[:12]}"

    responses = fire_together([lambda: post(client, headers, payload, key) for _ in range(20)])
    counts = Counter(response.status_code for response in responses)

    # One creation; the rest replay it. Nothing may fail.
    assert counts[201] == 1, f"expected exactly one creation, got {counts}"
    assert counts[200] == 19, f"expected nineteen replays, got {counts}"

    identifiers = {response.json()["data"]["id"] for response in responses}
    assert len(identifiers) == 1, f"callers saw different bookings: {identifiers}"

    assert db.query(Booking).count() == 1
    assert db.query(IdempotencyRecord).count() == 1

    # The side effects are not duplicated either: one creation, one audit entry,
    # one notification - not twenty.
    assert db.query(AuditLog).filter_by(action="BOOKING_CREATED").count() == 1
    assert db.query(Notification).count() == 1


@pytest.mark.parametrize("attempt", range(3))
def test_twenty_distinct_keys_create_twenty_bookings(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Idempotency must not accidentally collapse genuinely different requests."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])

    calls = [
        (
            lambda index=index: post(  # type: ignore[misc]
                client,
                headers,
                body(setup, days=5 + index),
                f"stress-multi-{index}-{uuid.uuid4().hex[:8]}",
            )
        )
        for index in range(20)
    ]
    responses = fire_together(calls)

    counts = Counter(response.status_code for response in responses)
    assert counts[201] == 20, f"every distinct request must be created, got {counts}"
    assert db.query(Booking).count() == 20
    assert db.query(IdempotencyRecord).count() == 20
    assert len({response.json()["data"]["id"] for response in responses}) == 20


@pytest.mark.parametrize("attempt", range(3))
def test_one_key_with_two_payloads_creates_one_booking_and_refuses_the_other(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Ten callers, one key, two different payloads, all at once."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    key = f"stress-conflict-{uuid.uuid4().hex[:12]}"
    first, second = body(setup, days=6), body(setup, days=9)

    calls = [
        (lambda payload=payload: post(client, headers, payload, key))  # type: ignore[misc]
        for payload in ([first, second] * 5)
    ]
    responses = fire_together(calls)
    counts = Counter(response.status_code for response in responses)

    # Whichever payload wins the race, exactly one booking exists, everyone with
    # that payload sees it, and everyone with the other is told it conflicts.
    assert counts[201] == 1, f"expected one creation, got {counts}"
    assert counts[200] + counts[409] == 9, counts
    assert counts[409] >= 1, f"the other payload must be refused, got {counts}"
    assert db.query(Booking).count() == 1
    assert db.query(AuditLog).filter_by(action="BOOKING_CREATED").count() == 1

    for response in responses:
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("attempt", range(3))
def test_a_retry_while_the_first_attempt_is_in_flight_never_doubles_up(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Impatient retries: the same key resent while the original is still running.

    Every caller must end up with the one booking, or be told plainly that the
    request is already being processed. Two bookings is the one unacceptable
    outcome.
    """
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    payload = body(setup, days=7)
    key = f"stress-inflight-{uuid.uuid4().hex[:12]}"

    def burst() -> list[Any]:
        return fire_together([lambda: post(client, headers, payload, key) for _ in range(6)])

    waves = fire_together([burst, burst], timeout=60)
    responses = [response for wave in waves for response in wave]

    counts = Counter(response.status_code for response in responses)
    assert counts[201] == 1, f"expected exactly one creation across both waves, got {counts}"
    assert counts[201] + counts[200] + counts[409] == 12, counts
    assert db.query(Booking).count() == 1
    assert db.query(IdempotencyRecord).count() == 1
    assert db.query(AuditLog).filter_by(action="BOOKING_CREATED").count() == 1

    for response in responses:
        if response.status_code == 200:
            assert response.headers.get("Idempotent-Replay") == "true"


@pytest.mark.parametrize("attempt", range(3))
def test_separate_customers_reusing_one_key_do_not_collide(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """The key is scoped to the caller, so two people can pick the same string."""
    first = booking_setup(db, organization)
    second = booking_setup(db, organization)
    key = "the-same-key-for-everyone"

    responses = fire_together(
        [
            lambda: post(client, auth_headers(client, first["customer_user"]), body(first), key),
            lambda: post(
                client, auth_headers(client, second["customer_user"]), body(second, days=8), key
            ),
        ]
    )

    assert [response.status_code for response in responses] == [201, 201]
    assert db.query(Booking).count() == 2
    assert db.query(IdempotencyRecord).count() == 2
