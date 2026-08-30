"""The Celery application.

Redis is both broker and result backend - it already runs for the rest of the
stack, and the queue depth here is small enough that a dedicated broker would be
operational weight with nothing to show for it.

Started with:
    uv run celery -A serviceflow.worker.celery_app worker --beat --loglevel=info
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import setup_logging

from serviceflow.core.config import get_settings
from serviceflow.core.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "serviceflow",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["serviceflow.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Redelivered if a worker dies mid-task, which is what makes the outbox
    # at-least-once rather than at-most-once.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    # Nothing consumes task results: the API queues and forgets, and durable
    # state lives in the notifications table. Storing them made the API hold a
    # result-store connection it never read, which during a Redis outage
    # produced "the Celery application must be restarted" errors about a
    # subsystem the API does not use.
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Catches EMAIL rows whose dispatch was never queued - a broker outage
        # right after the business commit, or a worker lost mid-flight.
        "sweep-pending-emails": {
            "task": "serviceflow.sweep_pending_emails",
            "schedule": 60.0,
        },
        # Reminder creation is idempotent, so the cadence only affects latency.
        "queue-appointment-reminders": {
            "task": "serviceflow.queue_appointment_reminders",
            "schedule": 300.0,
        },
        # Idempotency keys are kept for 24 hours; this is what enforces that.
        # Hourly is ample - the retention window is a day, and each run deletes
        # in bounded batches.
        "purge-expired-idempotency-keys": {
            "task": "serviceflow.purge_expired_idempotency_keys",
            "schedule": 3600.0,
        },
    },
)


@setup_logging.connect  # type: ignore[untyped-decorator]
def _configure_worker_logging(**_: object) -> None:
    """Use the app's structured JSON logging in workers too, secrets redacted."""
    configure_logging("DEBUG" if settings.debug else "INFO")
    logging.getLogger("celery").setLevel(logging.INFO)
