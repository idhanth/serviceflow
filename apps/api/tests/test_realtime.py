"""Realtime events: what gets published, and who is allowed to receive it.

Publishing runs against the real Redis the rest of the stack uses; the envelope
filtering is pure and tested directly, which is what actually decides isolation.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import Role
from serviceflow.db.models.organization import Organization
from serviceflow.services import outbox, realtime
from serviceflow.services.realtime import RealtimeEvent
from tests.conftest import (
    auth_headers,
    booking_setup,
    future_start,
    job_with_parties,
    make_booking,
    make_user,
)


@pytest.fixture()
def captured(monkeypatch) -> list[RealtimeEvent]:  # type: ignore[no-untyped-def]
    """Collect what the outbox would broadcast, without a subscriber."""
    events: list[RealtimeEvent] = []
    monkeypatch.setattr(outbox, "publish", lambda event: events.append(event) or True)
    return events


# ------------------------------------------------------------------ envelope


def test_an_event_carries_no_record_content() -> None:
    """Envelopes name what changed; the client refetches the record itself."""
    event = realtime.booking_updated(
        organization_id=uuid.uuid4(),
        booking_id=uuid.uuid4(),
        customer_user_id=uuid.uuid4(),
    )
    payload = event.to_json()
    for leaky in ("email", "notes", "price", "phone", "address", "subject", "body"):
        assert leaky not in payload


def test_a_recipient_receives_and_a_stranger_does_not() -> None:
    target, stranger = uuid.uuid4(), uuid.uuid4()
    event = realtime.notification_created(
        organization_id=uuid.uuid4(), user_id=target, notification_id=uuid.uuid4()
    )
    assert event.visible_to(user_id=target, roles=["CUSTOMER"])
    assert not event.visible_to(user_id=stranger, roles=["CUSTOMER"])
    # A notification is addressed to one person - not even an admin sees it.
    assert not event.visible_to(user_id=stranger, roles=["ADMIN"])


def test_admins_receive_operational_events_by_role() -> None:
    event = realtime.job_updated(organization_id=uuid.uuid4(), job_id=uuid.uuid4())
    assert event.visible_to(user_id=uuid.uuid4(), roles=["ADMIN"])
    assert not event.visible_to(user_id=uuid.uuid4(), roles=["EMPLOYEE"])
    assert not event.visible_to(user_id=uuid.uuid4(), roles=["CUSTOMER"])


def test_the_assigned_employee_and_the_customer_receive_job_events() -> None:
    customer, employee, bystander = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    event = realtime.job_updated(
        organization_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        customer_user_id=customer,
        employee_user_id=employee,
    )
    assert event.visible_to(user_id=customer, roles=["CUSTOMER"])
    assert event.visible_to(user_id=employee, roles=["EMPLOYEE"])
    assert not event.visible_to(user_id=bystander, roles=["EMPLOYEE"])


def test_each_organization_has_its_own_channel() -> None:
    one, two = uuid.uuid4(), uuid.uuid4()
    assert realtime.channel_for(one) != realtime.channel_for(two)
    assert str(one) in realtime.channel_for(one)


def test_a_malformed_payload_is_discarded_not_raised() -> None:
    assert RealtimeEvent.from_json("not json") is None
    assert RealtimeEvent.from_json('{"unexpected": true}') is None


def test_publishing_reaches_a_real_redis_subscriber() -> None:
    """Round-trips through the actual broker, not an in-process list."""
    import redis

    from serviceflow.core.config import get_settings

    organization_id = uuid.uuid4()
    client = redis.Redis.from_url(str(get_settings().redis_url))
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(realtime.channel_for(organization_id))
    try:
        event = realtime.booking_updated(organization_id=organization_id, booking_id=uuid.uuid4())
        assert realtime.publish(event) is True

        received = None
        for _ in range(50):
            message = pubsub.get_message(timeout=0.2)
            if message and message.get("type") == "message":
                received = RealtimeEvent.from_json(message["data"].decode())
                break
        assert received is not None, "no event arrived over Redis"
        assert received.resource_id == event.resource_id
    finally:
        pubsub.close()
        client.close()


# ------------------------------------------------------------------ publishing


def test_confirming_a_booking_publishes_an_event(
    client: TestClient, db: Session, organization: Organization, captured: list
) -> None:
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

    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=auth_headers(client, admin),
        json={"employee_id": str(setup["employee"].id)},
    )

    kinds = [event.type for event in captured]
    assert "booking.updated" in kinds
    assert "notification.created" in kinds

    booking_event = next(e for e in captured if e.type == "booking.updated")
    assert booking_event.resource_id == str(booking.id)
    assert str(setup["customer_user"].id) in booking_event.recipients
    assert "ADMIN" in booking_event.roles


def test_starting_and_completing_a_job_publish_events(
    client: TestClient, db: Session, organization: Organization, captured: list
) -> None:
    parties = job_with_parties(db, organization)
    staff = auth_headers(client, parties["employee_user"])

    client.post(f"/api/v1/jobs/{parties['job'].id}/start", headers=staff)
    client.post(f"/api/v1/jobs/{parties['job'].id}/complete", headers=staff, json={})

    job_events = [e for e in captured if e.type == "job.updated"]
    assert len(job_events) == 2
    for event in job_events:
        assert event.resource_id == str(parties["job"].id)
        assert str(parties["customer_user"].id) in event.recipients
        assert str(parties["employee_user"].id) in event.recipients


def test_a_rolled_back_action_publishes_nothing(
    client: TestClient, db: Session, organization: Organization, captured: list
) -> None:
    from serviceflow.core.errors import DependencyUnavailable
    from serviceflow.services.scheduling import (
        AssignmentRequest,
        get_scheduling_policy,
        set_scheduling_policy,
    )

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
        client.post(
            f"/api/v1/bookings/{booking.id}/confirm",
            headers=auth_headers(client, admin),
            json={"employee_id": str(setup["employee"].id)},
        )
    finally:
        set_scheduling_policy(previous)

    assert [e for e in captured if e.type == "booking.updated"] == []


def test_a_publish_failure_does_not_fail_the_request(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """Redis being down must not turn a committed booking into an error."""

    def explode(event: RealtimeEvent) -> bool:
        raise ConnectionError("redis is gone")

    monkeypatch.setattr(realtime, "_publisher", explode)

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
    assert response.json()["data"]["status"] == "CONFIRMED"


# ------------------------------------------------------------------ the stream


def test_the_stream_refuses_an_unauthenticated_client(client: TestClient) -> None:
    assert client.get("/api/v1/events").status_code == 401


def test_the_stream_refuses_a_tampered_token(
    client: TestClient, db: Session, organization: Organization
) -> None:
    admin = make_user(db, organization, role=Role.ADMIN)
    headers = auth_headers(client, admin)
    headers["Authorization"] = headers["Authorization"][:-3] + "aaa"
    assert client.get("/api/v1/events", headers=headers).status_code == 401


def test_the_stream_refuses_a_foreign_organization_header(
    client: TestClient, db: Session, organization: Organization
) -> None:
    from tests.conftest import make_organization

    admin = make_user(db, organization, role=Role.ADMIN)
    rival = make_organization(db, name="Rival Detailing")
    headers = {**auth_headers(client, admin), "X-Organization-Id": str(rival.id)}
    assert client.get("/api/v1/events", headers=headers).status_code == 403


class _StubRequest:
    """A request that reports itself disconnected after a set number of checks.

    TestClient cannot drive an endless SSE generator - it has no way to hang up -
    so the generator is exercised directly with a request that does.
    """

    def __init__(self, disconnect_after: int) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


@pytest.mark.asyncio
async def test_the_stream_sends_its_opening_frames_then_stops_on_disconnect(
    db: Session, organization: Organization
) -> None:
    from serviceflow.api.v1.events import _stream
    from serviceflow.auth.principal import CurrentUser

    admin = make_user(db, organization, role=Role.ADMIN)
    principal = CurrentUser(
        user_id=admin.id,
        organization_id=organization.id,
        email=admin.email,
        full_name=admin.full_name,
        roles=frozenset({Role.ADMIN}),
    )

    frames: list[bytes] = []
    async for frame in _stream(_StubRequest(disconnect_after=0), principal, 1):
        frames.append(frame)
        if len(frames) > 5:  # pragma: no cover - guards a runaway generator
            break

    opening = b"".join(frames).decode()
    # The retry hint is what makes EventSource reconnect on its own.
    assert "retry: 3000" in opening
    assert ": connected" in opening


@pytest.mark.asyncio
async def test_the_stream_delivers_a_matching_event_and_filters_the_rest(
    db: Session, organization: Organization, monkeypatch
) -> None:
    """One connection, two events: only the one addressed to this user arrives."""
    from serviceflow.api.v1 import events as events_module
    from serviceflow.auth.principal import CurrentUser

    customer = make_user(db, organization, role=Role.CUSTOMER)
    mine = realtime.notification_created(
        organization_id=organization.id, user_id=customer.id, notification_id=uuid.uuid4()
    )
    theirs = realtime.notification_created(
        organization_id=organization.id, user_id=uuid.uuid4(), notification_id=uuid.uuid4()
    )

    async def fake_subscribe(organization_id):  # type: ignore[no-untyped-def]
        yield theirs
        yield mine

    monkeypatch.setattr(events_module.realtime, "subscribe", fake_subscribe)

    principal = CurrentUser(
        user_id=customer.id,
        organization_id=organization.id,
        email=customer.email,
        full_name=customer.full_name,
        roles=frozenset({Role.CUSTOMER}),
    )

    payloads: list[str] = []
    async for frame in events_module._stream(_StubRequest(disconnect_after=10), principal, 1):
        text = frame.decode()
        if text.startswith("data: "):
            payloads.append(text)
            break

    assert len(payloads) == 1
    assert mine.resource_id in payloads[0]
    assert theirs.resource_id not in payloads[0]


# ------------------------------------------------------------------ degradation


def test_readiness_reports_redis_as_a_dependency(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """Redis being down makes the app not-ready, but still alive and serving."""
    import redis as redis_module

    from serviceflow.api.v1 import health

    class DeadRedis:
        def ping(self) -> bool:
            raise ConnectionError("redis is gone")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        health.redis.Redis, "from_url", classmethod(lambda cls, *a, **k: DeadRedis())
    )

    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["redis"] == "unavailable"
    assert ready.json()["checks"]["database"] == "ok"

    # Liveness is unaffected, and database-backed reads keep working.
    assert client.get("/health").json() == {"status": "ok"}
    admin = make_user(db, organization, role=Role.ADMIN)
    assert client.get("/api/v1/customers", headers=auth_headers(client, admin)).status_code == 200
    assert redis_module is not None


def test_a_committed_action_survives_a_dead_broker(
    client: TestClient, db: Session, organization: Organization, monkeypatch
) -> None:
    """Queueing failure leaves the email in the outbox rather than failing the API."""
    from serviceflow.db.models.enums import NotificationChannel, NotificationStatus
    from serviceflow.db.models.notification import Notification
    from serviceflow.worker import tasks

    def dead_delay(notification_id: str) -> None:
        raise ConnectionError("broker is gone")

    monkeypatch.setattr(tasks.dispatch_email, "delay", dead_delay)

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

    # The row is still there for the sweep to find.
    pending = (
        db.query(Notification)
        .filter_by(channel=NotificationChannel.EMAIL, status=NotificationStatus.PENDING)
        .count()
    )
    assert pending == 1


def test_the_infrastructure_probe_reports_delivery_and_queue_health(
    client: TestClient, db: Session, organization: Organization
) -> None:
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
    headers = auth_headers(client, admin)
    client.post(
        f"/api/v1/bookings/{booking.id}/confirm",
        headers=headers,
        json={"employee_id": str(setup["employee"].id)},
    )

    body = client.get("/api/v1/infrastructure", headers=headers).json()["data"]
    assert body["email"]["pending"] == 1
    assert body["email"]["failed"] == 0
    assert body["queue"]["reachable"] is True
    assert body["realtime"]["reachable"] is True


def test_only_admins_see_infrastructure_health(
    client: TestClient, db: Session, organization: Organization
) -> None:
    parties = job_with_parties(db, organization)
    for user in (parties["customer_user"], parties["employee_user"]):
        assert (
            client.get("/api/v1/infrastructure", headers=auth_headers(client, user)).status_code
            == 403
        )
