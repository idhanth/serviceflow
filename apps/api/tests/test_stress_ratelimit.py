"""The limiter under many simultaneous callers (PRD 42, phase 8).

The claim being tested is that the boundary holds because INCR, EXPIRE and TTL
happen as one operation in Redis - not because requests happen to arrive in a
convenient order. So these run real threads against the real server; an
in-memory stand-in would prove nothing about the thing that actually enforces
the limit in production.
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

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.services.ratelimit import LIMITS, Limit, check
from tests.conftest import auth_headers, booking_setup, future_start, make_user

pytestmark = [pytest.mark.concurrency, pytest.mark.stress, pytest.mark.usefixtures("rate_limiting")]


def fire_together(calls: list[Any], timeout: float = 45.0) -> list[Any]:
    barrier = threading.Barrier(len(calls))

    def run(call: Any) -> Any:
        barrier.wait(timeout=20)
        return call()

    # One worker per call: the barrier needs every party to arrive, so a pool
    # smaller than the barrier deadlocks and breaks it.
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=timeout) for f in [pool.submit(run, c) for c in calls]]


@pytest.mark.parametrize("attempt", range(3))
def test_a_hundred_callers_cannot_exceed_a_limit_of_twenty(attempt: int) -> None:
    """The boundary is exact, not approximate, however many arrive together."""
    limit = Limit(
        name="search", max_requests=20, window_seconds=60, fail_closed=False, message="slow down"
    )
    identity = f"stress-{uuid.uuid4().hex[:10]}"

    results = fire_together([lambda: check(limit, identity).allowed for _ in range(100)])
    assert sum(results) == 20, f"expected exactly 20 allowed, got {sum(results)}"


@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_callers_never_lose_the_expiry(attempt: int) -> None:
    """A key must always carry a TTL.

    Incrementing and expiring as two round trips leaves a key with no expiry
    whenever a caller dies between them - a limiter that never resets. The Lua
    script makes that unreachable, and this is the check that says so.
    """
    import redis

    from serviceflow.core.config import get_settings

    limit = Limit(name="search", max_requests=50, window_seconds=45, fail_closed=False, message="x")
    identity = f"ttl-{uuid.uuid4().hex[:10]}"
    fire_together([lambda: check(limit, identity) for _ in range(40)])

    client = redis.Redis.from_url(str(get_settings().redis_url))
    try:
        ttl = client.ttl(f"sf:rl:search:{identity}")
    finally:
        client.close()
    assert 0 < ttl <= 45, f"the window must always expire; ttl was {ttl}"


@pytest.mark.parametrize("attempt", range(3))
def test_simultaneous_bookings_from_one_customer_stop_at_the_limit(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Through the API, not just the limiter: fired all at once."""
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    allowed = LIMITS["booking_create"].max_requests

    calls = [
        (
            lambda index=index: client.post(  # type: ignore[misc]
                "/api/v1/bookings",
                headers=headers,
                json={
                    "service_id": str(setup["service"].id),
                    "requested_start": future_start(days=3 + index).isoformat(),
                },
            )
        )
        for index in range(allowed + 15)
    ]
    responses = fire_together(calls, timeout=90)
    counts = Counter(response.status_code for response in responses)

    assert counts[201] <= allowed, f"the limit was exceeded under load: {counts}"
    assert counts[429] >= 15, f"expected the surplus to be refused, got {counts}"
    for response in responses:
        if response.status_code == 429:
            assert response.json()["error"]["code"] == "RATE_LIMITED"
            assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize("attempt", range(3))
def test_two_customers_under_load_keep_their_own_budgets(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """One caller exhausting their quota must not spend anyone else's."""
    heavy = booking_setup(db, organization)
    quiet = booking_setup(db, organization)
    heavy_headers = auth_headers(client, heavy["customer_user"])
    allowed = LIMITS["booking_create"].max_requests

    fire_together(
        [
            (
                lambda index=index: client.post(  # type: ignore[misc]
                    "/api/v1/bookings",
                    headers=heavy_headers,
                    json={
                        "service_id": str(heavy["service"].id),
                        "requested_start": future_start(days=3 + index).isoformat(),
                    },
                )
            )
            for index in range(allowed + 10)
        ],
        timeout=90,
    )

    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, quiet["customer_user"]),
        json={
            "service_id": str(quiet["service"].id),
            "requested_start": future_start(days=2).isoformat(),
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("attempt", range(3))
def test_categories_under_load_do_not_share_a_counter(
    client: TestClient, db: Session, organization: Organization, attempt: int
) -> None:
    """Exhausting one limiter must leave the others untouched."""
    admin = make_user(db, organization, role=Role.OWNER)
    headers = auth_headers(client, admin)
    allowed = LIMITS["search"].max_requests

    # Sequential on purpose: this is about isolation between categories, and the
    # boundary race is covered above without spawning 140 threads.
    for _ in range(allowed + 2):
        client.get("/api/v1/search?q=maria", headers=headers)
    assert client.get("/api/v1/search?q=maria", headers=headers).status_code == 429

    # A different category, same user, still fine.
    assert client.get("/api/v1/customers?page_size=1", headers=headers).status_code == 200
