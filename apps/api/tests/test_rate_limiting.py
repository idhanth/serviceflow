"""Rate limiting (PRD 42), exercised against real Redis.

The point of the limiter is that it is atomic across processes; a test that
counted in Python would prove nothing about that, so every case here goes
through the real Lua script on the real server.
"""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.services import ratelimit
from serviceflow.services.ratelimit import LIMITS, Limit, check
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_organization,
    make_user,
)

pytestmark = pytest.mark.usefixtures("rate_limiting")


def dead_client():  # type: ignore[no-untyped-def]
    """Stands in for the cached client factory when Redis is unreachable."""

    def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ConnectionError("redis is gone")

    factory.cache_clear = lambda: None  # type: ignore[attr-defined]
    return factory


def signup_body(organization: Organization, email: str) -> dict:
    return {
        "organization_slug": organization.slug,
        "email": email,
        "password": "a-good-password",
        "first_name": "Rate",
        "last_name": "Limited",
    }


# ------------------------------------------------------------------ the counter


def test_the_limiter_counts_and_then_refuses() -> None:
    limit = Limit(
        name="search", max_requests=3, window_seconds=60, fail_closed=False, message="slow down"
    )
    identity = "unit-test-counter"

    decisions = [check(limit, identity) for _ in range(5)]
    assert [d.allowed for d in decisions] == [True, True, True, False, False]
    # The boundary: the third request is the last allowed one.
    assert decisions[2].remaining == 0
    assert decisions[3].retry_after > 0


def test_separate_identities_have_separate_budgets() -> None:
    limit = LIMITS["search"]
    first = [check(limit, "identity-a") for _ in range(3)]
    second = check(limit, "identity-b")

    assert all(d.allowed for d in first)
    # A fresh identity starts at the top of its own window.
    assert second.remaining == limit.max_requests - 1


def test_separate_limiter_categories_do_not_share_a_counter() -> None:
    identity = "same-person"
    search = check(LIMITS["search"], identity)
    booking = check(LIMITS["booking_create"], identity)

    assert search.remaining == LIMITS["search"].max_requests - 1
    assert booking.remaining == LIMITS["booking_create"].max_requests - 1


def test_the_window_expires() -> None:
    """The key carries a TTL, so a budget is not consumed forever."""
    import redis

    from serviceflow.core.config import get_settings

    limit = Limit(name="search", max_requests=1, window_seconds=30, fail_closed=False, message="x")
    check(limit, "expiring-identity")

    client = redis.Redis.from_url(str(get_settings().redis_url))
    try:
        ttl = client.ttl("sf:rl:search:expiring-identity")
        assert 0 < ttl <= 30
    finally:
        client.close()


@pytest.mark.concurrency
@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_requests_cannot_exceed_the_limit(attempt: int) -> None:
    """The whole reason for the Lua script: INCR and EXPIRE as one operation."""
    limit = Limit(name="search", max_requests=10, window_seconds=60, fail_closed=False, message="x")
    identity = f"race-{attempt}"
    barrier = threading.Barrier(30)

    def attempt_once() -> bool:
        barrier.wait(timeout=15)
        return check(limit, identity).allowed

    with ThreadPoolExecutor(max_workers=30) as pool:
        results = [f.result(timeout=30) for f in [pool.submit(attempt_once) for _ in range(30)]]

    assert sum(results) == 10, f"expected exactly 10 to pass, got {sum(results)}"


# ------------------------------------------------------------------ endpoints


def test_signup_is_limited_by_source_address(
    client: TestClient, db: Session, organization: Organization
) -> None:
    allowed = LIMITS["signup"].max_requests
    statuses = [
        client.post(
            "/api/v1/auth/signup", json=signup_body(organization, f"rate{index}@example.com")
        ).status_code
        for index in range(allowed + 2)
    ]

    assert statuses[:allowed] == [201] * allowed
    assert statuses[allowed] == 429
    assert statuses[allowed + 1] == 429


def test_a_limited_response_is_well_formed(
    client: TestClient, db: Session, organization: Organization
) -> None:
    for index in range(LIMITS["signup"].max_requests):
        client.post(
            "/api/v1/auth/signup", json=signup_body(organization, f"shape{index}@example.com")
        )

    response = client.post(
        "/api/v1/auth/signup", json=signup_body(organization, "over@example.com")
    )
    assert response.status_code == 429

    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["request_id"].startswith("req_")
    assert "try again" in error["message"].lower()
    assert int(response.headers["Retry-After"]) > 0

    # Nothing about the limiter's internals reaches the caller.
    body = response.text.lower()
    for leak in ("redis", "sf:rl", "lua", "incr", "ttl", "traceback"):
        assert leak not in body


def test_login_is_limited(client: TestClient, db: Session, organization: Organization) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    payload = {"email": user.email, "password": "wrong-password"}

    statuses = [
        client.post("/api/v1/auth/login", json=payload).status_code
        for _ in range(LIMITS["login"].max_requests + 1)
    ]
    assert statuses[-1] == 429
    assert statuses[0] == 401


def test_booking_creation_is_limited_per_user(
    client: TestClient, db: Session, organization: Organization
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    allowed = LIMITS["booking_create"].max_requests

    statuses = []
    for index in range(allowed + 1):
        statuses.append(
            client.post(
                "/api/v1/bookings",
                headers=headers,
                json={
                    "vehicle_id": str(setup["vehicle"].id),
                    "service_id": str(setup["service"].id),
                    "requested_start": future_start(days=3 + index % 20).isoformat(),
                },
            ).status_code
        )

    assert statuses[-1] == 429
    assert statuses.count(201) == allowed


def test_one_user_does_not_consume_anothers_quota(
    client: TestClient, db: Session, organization: Organization
) -> None:
    first = booking_setup(db, organization)
    second = booking_setup(db, organization)
    first_headers = auth_headers(client, first["customer_user"])

    for index in range(LIMITS["booking_create"].max_requests + 1):
        client.post(
            "/api/v1/bookings",
            headers=first_headers,
            json={
                "vehicle_id": str(first["vehicle"].id),
                "service_id": str(first["service"].id),
                "requested_start": future_start(days=3 + index % 20).isoformat(),
            },
        )

    # The second customer is untouched by the first one's spending.
    response = client.post(
        "/api/v1/bookings",
        headers=auth_headers(client, second["customer_user"]),
        json={
            "vehicle_id": str(second["vehicle"].id),
            "service_id": str(second["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 201


def test_organizations_have_separate_quotas(
    client: TestClient, db: Session, organization: Organization
) -> None:
    ours = booking_setup(db, organization)
    rival = make_organization(db, name="Rival Detailing")
    theirs = booking_setup(db, rival)
    our_headers = auth_headers(client, ours["customer_user"], organization)
    their_headers = auth_headers(client, theirs["customer_user"], rival)

    for index in range(LIMITS["booking_create"].max_requests + 1):
        client.post(
            "/api/v1/bookings",
            headers=our_headers,
            json={
                "vehicle_id": str(ours["vehicle"].id),
                "service_id": str(ours["service"].id),
                "requested_start": future_start(days=3 + index % 20).isoformat(),
            },
        )

    response = client.post(
        "/api/v1/bookings",
        headers=their_headers,
        json={
            "vehicle_id": str(theirs["vehicle"].id),
            "service_id": str(theirs["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 201


def test_photo_presign_is_limited(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    headers = auth_headers(client, parties["employee_user"])
    allowed = LIMITS["photo_presign"].max_requests

    statuses = [
        client.post(
            f"/api/v1/jobs/{parties['job'].id}/photos/presign",
            headers=headers,
            json={"mime_type": "image/png", "file_size": 100},
        ).status_code
        for _ in range(allowed + 1)
    ]
    assert statuses[-1] == 429


def test_search_is_limited(client: TestClient, db: Session, organization: Organization) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    allowed = LIMITS["search"].max_requests

    statuses = [
        client.get("/api/v1/search?q=alice", headers=headers).status_code
        for _ in range(allowed + 1)
    ]
    assert statuses[-1] == 429
    assert Counter(statuses)[200] == allowed


def test_unlimited_endpoints_are_not_accidentally_caught(
    client: TestClient, db: Session, organization: Organization
) -> None:
    """Reads that carry no abuse risk keep working past every limiter's ceiling."""
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    statuses = {
        client.get("/api/v1/customers?page_size=1", headers=headers).status_code
        for _ in range(LIMITS["search"].max_requests + 5)
    }
    assert statuses == {200}


# ------------------------------------------------------------------ outage policy


def test_abuse_sensitive_limits_fail_closed_without_redis(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Signup and login refuse rather than run unprotected."""
    monkeypatch.setattr(ratelimit, "_client", dead_client())

    for name in ("signup", "login"):
        decision = check(LIMITS[name], "anyone")
        assert decision.allowed is False, name


def test_authenticated_limits_fail_open_without_redis(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A known user keeps working; the product does not go down with Redis."""
    monkeypatch.setattr(ratelimit, "_client", dead_client())

    for name in ("booking_create", "photo_presign", "search"):
        decision = check(LIMITS[name], "someone")
        assert decision.allowed is True, name


def test_signup_is_refused_end_to_end_when_redis_is_down(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    monkeypatch.setattr(ratelimit, "_client", dead_client())

    response = client.post(
        "/api/v1/auth/signup", json=signup_body(organization, "outage@example.com")
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_database_reads_still_work_when_the_limiter_is_down(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """Phase 6's guarantee holds: Redis is not required to read a booking."""

    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)  # sign in while Redis is still up
    monkeypatch.setattr(ratelimit, "_client", dead_client())

    assert client.get("/api/v1/customers", headers=headers).status_code == 200
    assert client.get("/api/v1/search?q=alice", headers=headers).status_code == 200
