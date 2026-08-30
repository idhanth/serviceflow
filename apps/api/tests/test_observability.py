"""Request correlation and structured logging (PRD 43).

These tests read the JSON a log line actually renders to, not the LogRecord, so
that a formatter change which drops the correlation fields or starts emitting a
secret is caught here rather than in production.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.core import context as request_context
from serviceflow.core.logging import ContextJsonFormatter
from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.services import ratelimit
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    make_user,
)


def dead_client(detail: str = "redis is gone"):  # type: ignore[no-untyped-def]
    """A stand-in for the cached Redis client factory that refuses to connect."""

    def factory(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError(detail)

    factory.cache_clear = lambda: None  # type: ignore[attr-defined]
    return factory


class CapturingHandler(logging.Handler):
    """Keeps the rendered JSON, which is what actually ships to the log."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(ContextJsonFormatter("%(timestamp)s %(level)s %(logger)s %(message)s"))
        self.lines: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))

    def named(self, logger_name: str) -> list[dict[str, Any]]:
        return [line for line in self.lines if line.get("logger") == logger_name]

    @property
    def text(self) -> str:
        return json.dumps(self.lines)


@pytest.fixture
def logs() -> Iterator[CapturingHandler]:
    handler = CapturingHandler()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


# ------------------------------------------------------------------ request ids


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["X-Request-Id"].startswith("req_")


def test_an_incoming_request_id_is_honoured(client: TestClient) -> None:
    """A gateway's id wins, so one trace spans the whole hop."""
    response = client.get("/health", headers={"X-Request-Id": "trace-from-the-edge"})
    assert response.headers["X-Request-Id"] == "trace-from-the-edge"


def test_an_absurd_incoming_request_id_is_truncated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-Id": "x" * 5000})
    assert len(response.headers["X-Request-Id"]) == 64


def test_the_error_body_and_the_header_agree(client: TestClient) -> None:
    response = client.get("/api/v1/customers")
    assert response.status_code == 401
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


def test_request_ids_differ_between_requests(client: TestClient) -> None:
    ids = {client.get("/health").headers["X-Request-Id"] for _ in range(5)}
    assert len(ids) == 5


# ------------------------------------------------------------------ log content


def test_an_access_log_line_carries_the_request_id(
    client: TestClient, logs: CapturingHandler
) -> None:
    client.get("/health", headers={"X-Request-Id": "trace-health"})
    access = logs.named("serviceflow.access")
    assert access, "no access log line was emitted"
    assert access[-1]["request_id"] == "trace-health"
    assert access[-1]["status"] == 200
    assert access[-1]["path"] == "/health"
    assert access[-1]["duration_ms"] >= 0


def test_an_authenticated_request_logs_who_made_it(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    """The regression that motivated the ASGI rewrite: these were always null."""
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    logs.lines.clear()

    client.get("/api/v1/customers", headers=headers)

    line = logs.named("serviceflow.access")[-1]
    assert line["user_id"] == str(admin.id)
    assert line["organization_id"] == str(organization.id)


def test_an_unauthenticated_request_logs_no_actor(
    client: TestClient, logs: CapturingHandler
) -> None:
    client.get("/health")
    line = logs.named("serviceflow.access")[-1]
    assert line["user_id"] is None
    assert line["organization_id"] is None


def test_context_does_not_leak_between_requests(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    client.get("/api/v1/customers", headers=auth_headers(client, admin))
    logs.lines.clear()

    client.get("/health")

    assert logs.named("serviceflow.access")[-1]["user_id"] is None


# ------------------------------------------------------------------ failure paths


def test_an_internal_error_is_logged_with_context_and_hidden_from_the_client(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    from serviceflow.services import customers as customer_service

    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("password=hunter2 host=/var/secrets/db.pem SELECT * FROM users")

    original = customer_service.list_customers
    customer_service.list_customers = explode  # type: ignore[assignment]
    logs.lines.clear()
    try:
        # The app must render the 500 itself rather than re-raising into the test.
        with TestClient(client.app, raise_server_exceptions=False) as strict:
            response = strict.get("/api/v1/customers", headers=headers)
    finally:
        customer_service.list_customers = original  # type: ignore[assignment]

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    # None of the exception's contents survive the boundary.
    for leak in ("hunter2", "password", "SELECT", "var/secrets", "RuntimeError", "Traceback"):
        assert leak not in response.text, leak

    # But the operator gets everything needed to find it.
    logged = [line for line in logs.lines if line.get("message") == "unhandled exception"]
    assert logged, "the exception was not logged"
    assert logged[-1]["request_id"] == response.headers["X-Request-Id"]
    assert logged[-1]["exception_type"] == "RuntimeError"
    assert logged[-1]["user_id"] == str(admin.id)
    assert "exc_info" in logged[-1] or "Traceback" in logs.text


def test_a_failed_login_logs_no_password(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    user = make_user(db, organization, role=Role.ADMIN)
    logs.lines.clear()

    client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "correct-horse-battery-staple"},
    )

    assert "correct-horse-battery-staple" not in logs.text


def test_a_session_cookie_never_reaches_the_log(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    token = headers["Authorization"].split(" ", 1)[1]
    logs.lines.clear()

    client.get("/api/v1/customers", headers=headers)

    assert token not in logs.text
    assert "Bearer" not in logs.text


def test_a_scheduling_conflict_is_logged_as_a_business_outcome(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    setup = booking_setup(db, organization)
    headers = auth_headers(client, setup["customer_user"])
    logs.lines.clear()

    response = client.post(
        "/api/v1/bookings",
        headers=headers,
        json={
            "vehicle_id": str(setup["vehicle"].id),
            "service_id": str(setup["service"].id),
            "requested_start": future_start().isoformat(),
        },
    )
    assert response.status_code == 201

    line = logs.named("serviceflow.access")[-1]
    assert line["status"] == 201
    assert line["request_id"] == response.headers["X-Request-Id"]


@pytest.mark.usefixtures("rate_limiting")
def test_a_rate_limited_request_is_logged_without_the_redis_key(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    body = {
        "organization_slug": organization.slug,
        "email": "log{}@example.com",
        "password": "a-good-password",
        "first_name": "Log",
        "last_name": "Line",
    }
    for index in range(ratelimit.LIMITS["signup"].max_requests):
        client.post("/api/v1/auth/signup", json={**body, "email": f"log{index}@example.com"})
    logs.lines.clear()

    response = client.post("/api/v1/auth/signup", json={**body, "email": "over@example.com"})

    assert response.status_code == 429
    assert logs.named("serviceflow.access")[-1]["status"] == 429
    assert "sf:rl" not in logs.text
    assert "a-good-password" not in logs.text


@pytest.mark.usefixtures("rate_limiting")
def test_a_redis_outage_is_logged_but_not_returned(
    client: TestClient,
    db: Session,
    organization: Organization,
    logs: CapturingHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ratelimit, "_client", dead_client("redis://user:hunter2@10.0.0.5:6379"))
    logs.lines.clear()

    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "outage@example.com",
            "password": "a-good-password",
            "first_name": "O",
            "last_name": "U",
        },
    )

    assert response.status_code == 429
    assert "hunter2" not in response.text
    assert "10.0.0.5" not in response.text
    # The operator, unlike the caller, is told the limiter is degraded.
    assert any("rate limit" in str(line.get("message", "")).lower() for line in logs.lines)


def test_an_idempotency_conflict_is_logged_without_the_payload(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    setup = booking_setup(db, organization)
    headers = {**auth_headers(client, setup["customer_user"]), "Idempotency-Key": "log-conflict-1"}
    payload = {
        "vehicle_id": str(setup["vehicle"].id),
        "service_id": str(setup["service"].id),
        "requested_start": future_start().isoformat(),
    }
    client.post("/api/v1/bookings", headers=headers, json=payload)
    logs.lines.clear()

    conflicting = {**payload, "requested_start": future_start(days=9).isoformat()}
    response = client.post("/api/v1/bookings", headers=headers, json=conflicting)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert logs.named("serviceflow.access")[-1]["status"] == 409
    # The fingerprint is an implementation detail; the request body is private.
    assert "request_fingerprint" not in logs.text
    assert str(setup["vehicle"].id) not in logs.text


def test_a_validation_failure_does_not_echo_the_rejected_secret(
    client: TestClient, db: Session, organization: Organization, logs: CapturingHandler
) -> None:
    logs.lines.clear()
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "organization_slug": organization.slug,
            "email": "not-an-email",
            "password": "short",
            "first_name": "V",
            "last_name": "F",
        },
    )

    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert set(fields) == {"email", "password"}
    assert "short" not in response.text
    assert "short" not in logs.text


# ------------------------------------------------------------------ redaction


def test_the_formatter_redacts_sensitive_keys(logs: CapturingHandler) -> None:
    logging.getLogger("serviceflow.test").info(
        "attempt",
        extra={"password": "hunter2", "authorization": "Bearer abc", "email": "a@example.com"},
    )
    line = logs.named("serviceflow.test")[-1]
    assert line["password"] == "[redacted]"
    assert line["authorization"] == "[redacted]"
    assert line["email"] == "a@example.com"


# ------------------------------------------------------------------ correlation


def test_context_travels_to_background_work() -> None:
    """request_id -> business event -> Celery task is one chain."""
    request_context.bind_request("req_chain")
    request_context.bind_actor("user-1", "org-1")

    carried = request_context.current_context()
    assert carried == {
        "request_id": "req_chain",
        "user_id": "user-1",
        "organization_id": "org-1",
    }

    request_context.reset_request_context()
    assert request_context.current_context() == {}

    request_context.adopt_context(carried)  # what the worker does on the other side
    assert request_context.request_id() == "req_chain"
    assert request_context.user_id() == "user-1"
    request_context.reset_request_context()


def test_a_task_without_context_starts_clean() -> None:
    request_context.bind_request("stale")
    request_context.adopt_context(None)
    assert request_context.request_id() is None
