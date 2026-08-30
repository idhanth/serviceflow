"""A real Celery worker, a real Redis broker, a real SMTP server.

Everything else exercises the task functions directly, which is fast and covers
the logic. This file covers the wiring those tests assume: that a task queued
onto Redis is actually picked up by a separate worker process and that the email
really goes out. Mocking any part of that would prove nothing about deployment.

Marked `celery` so it can be deselected when the infrastructure is not running.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import time
from collections.abc import Iterator

import pytest
import redis
from celery import Celery
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import NotificationChannel, NotificationStatus, NotificationType
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.services import notifications
from tests.conftest import (
    TEST_DATABASE_URL,
    booking_setup,
    mailpit_clear,
    mailpit_messages,
)

pytestmark = pytest.mark.celery

# The worker must use the real broker, not the in-memory transport the rest of
# the suite runs on.
BROKER_URL = "redis://127.0.0.1:6380/2"


@pytest.fixture(scope="module")
def control_app() -> Celery:
    """A client app bound to the real broker.

    The suite's own celery_app is configured for the in-memory transport, and
    rebinding it after its connection is established does not take - so the
    integration test talks to the broker through its own app.
    """
    return Celery("serviceflow-itest", broker=BROKER_URL, backend=BROKER_URL)


@pytest.fixture(scope="module")
def worker(control_app: Celery) -> Iterator[subprocess.Popen]:
    """Start a real worker against a dedicated Redis database, then stop it."""
    client = redis.Redis.from_url(BROKER_URL)
    client.flushdb()
    client.close()

    env = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "SERVICEFLOW_BROKER_URL": BROKER_URL,
        "SERVICEFLOW_RESULT_BACKEND": BROKER_URL,
        "ENVIRONMENT": "test",
        "DEBUG": "false",
    }
    # Logs go to a file rather than a pipe: a pipe nobody drains fills up and
    # blocks the worker before it ever reaches ready.
    log_path = pathlib.Path(tempfile.gettempdir()) / "serviceflow-itest-worker.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "celery",
            "-A",
            "serviceflow.worker.celery_app",
            "worker",
            "--loglevel=info",
            "--concurrency=1",
            "--pool=solo",
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    )

    # Readiness is proved by a real task round trip rather than a pidbox ping:
    # the suite already imported the in-memory-transport app, which makes
    # broadcast control unreliable here, and a completed task is the stronger
    # signal anyway.
    deadline = time.time() + 60
    ready = False
    while time.time() < deadline and not ready:
        if process.poll() is not None:  # pragma: no cover - startup failure
            raise RuntimeError(f"worker exited early:\n{log_path.read_text()[-4000:]}")
        try:
            probe = control_app.send_task("serviceflow.sweep_pending_emails")
            probe.get(timeout=5)
            ready = True
        except Exception:
            time.sleep(0.5)

    if not ready:  # pragma: no cover
        process.terminate()
        raise RuntimeError(
            f"the celery worker never became reachable:\n{log_path.read_text()[-4000:]}"
        )

    yield process

    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover
        process.kill()
    log_file.close()


def _pending_email(db: Session, organization: Organization) -> Notification:
    setup = booking_setup(db, organization)
    notifications.enqueue(
        db,
        organization_id=organization.id,
        user_id=setup["customer_user"].id,
        type=NotificationType.JOB_COMPLETED,
        subject="Your detail is finished",
        body="Your vehicle is ready for collection.",
        payload={"booking_id": None},
        channels=(NotificationChannel.EMAIL,),
    )
    db.commit()
    return db.query(Notification).filter_by(channel=NotificationChannel.EMAIL).one()


def test_a_queued_task_is_executed_by_a_separate_worker_process(
    db: Session, organization: Organization, worker: subprocess.Popen, control_app: Celery
) -> None:
    """Queue onto Redis, and let the worker do the rest."""
    mailpit_clear()
    row = _pending_email(db, organization)

    # End this session's read transaction before handing the row to the worker.
    # A real request has released its connection by now; leaving one open makes
    # the worker's SELECT ... FOR UPDATE SKIP LOCKED pass the row over.
    row_id = row.id
    db.close()

    async_result = control_app.send_task("serviceflow.dispatch_email", args=[str(row_id)])
    # Either "sent" or "skipped" is correct: the outbox also queued a dispatch
    # when the transaction committed, and whichever arrives second finds the row
    # already settled. That is the at-least-once contract, and the assertions
    # below are what actually matters.
    assert async_result.get(timeout=30) in {"sent", "skipped"}

    deadline = time.time() + 20
    stored = None
    while time.time() < deadline:
        db.expire_all()
        stored = db.get(Notification, row_id)
        if stored is not None and stored.status is not NotificationStatus.PENDING:
            break
        time.sleep(0.3)

    assert stored is not None
    assert stored.status is NotificationStatus.SENT
    assert stored.sent_at is not None
    assert stored.failed_at is None

    # Duplicate dispatch must not mean a duplicate email.
    captured = mailpit_messages()
    assert len(captured) == 1, f"expected one email, got {len(captured)}"
    assert "finished" in captured[0]["Subject"]
    mailpit_clear()


def test_the_worker_executes_every_scheduled_task(
    worker: subprocess.Popen, control_app: Celery
) -> None:
    """Each task the beat schedule names is actually runnable in the worker."""
    for task_name in (
        "serviceflow.sweep_pending_emails",
        "serviceflow.queue_appointment_reminders",
    ):
        result = control_app.send_task(task_name)
        assert isinstance(result.get(timeout=30), int), task_name


def test_redis_really_is_the_broker(worker: subprocess.Popen, control_app: Celery) -> None:
    """Guards against this test silently using an in-memory transport."""
    assert str(control_app.conf.broker_url).startswith("redis://")
    client = redis.Redis.from_url(BROKER_URL)
    try:
        assert client.ping() is True
    finally:
        client.close()
