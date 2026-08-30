"""Notes, photos and notifications for the demo data (PRD 15, 16).

Photos are uploaded to the configured object storage for real - the same client
the API uses - so the demo shows genuine presigned reads rather than placeholder
images. If storage is unreachable the rest of the seed still completes; the
photos are simply skipped, and the message says so.
"""

from __future__ import annotations

import base64
import logging
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import (
    JobStatus,
    NoteVisibility,
    NotificationStatus,
    NotificationType,
    PhotoType,
)
from serviceflow.db.models.job import Job
from serviceflow.db.models.job_note import JobNote
from serviceflow.db.models.job_photo import JobPhoto
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.services.storage import get_object_storage

logger = logging.getLogger(__name__)

JOBS_WITH_CONTENT = 40
JOBS_WITH_PHOTOS = 12

# A 1x1 PNG. Small on purpose: the demo needs real objects in the bucket, not
# large ones.
SAMPLE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

INTERNAL_NOTES = [
    "Clay bar needed a second pass on the hood.",
    "Trim was already faded before we started - flagged to the customer.",
    "Used the softer pad on the rear quarter; paint reads thin there.",
    "Interior took longer than quoted, pet hair through the boot.",
    "Customer arrived late; started 20 minutes behind.",
]

CUSTOMER_NOTES = [
    "We removed the water spotting from the hood and roof.",
    "Leather has been cleaned and conditioned - it may feel slightly tacky for an hour.",
    "Wheels were decontaminated and sealed; brake dust should rinse off easily now.",
    "We treated the light swirl marks on the driver's door.",
    "All done - the paint has a fresh coat of sealant, good for about three months.",
]


def seed_job_content(db: Session, org: Organization, rng: random.Random) -> dict[str, int]:
    if db.scalar(
        select(func.count()).select_from(JobNote).where(JobNote.organization_id == org.id)
    ):
        return {"notes": 0, "photos": 0}

    completed = list(
        db.scalars(
            select(Job)
            .where(Job.organization_id == org.id, Job.status == JobStatus.COMPLETED)
            # Ties on the timestamp would otherwise resolve differently on each
            # rebuild, changing which jobs get content.
            .order_by(Job.scheduled_start.desc(), Job.scheduled_end.desc())
            .limit(JOBS_WITH_CONTENT)
        )
    )
    if not completed:
        return {"notes": 0, "photos": 0}

    notes = 0
    for job in completed:
        author_id = db.scalar(select(Employee.user_id).where(Employee.id == job.employee_id))
        if author_id is None:
            continue
        db.add(
            JobNote(
                organization_id=org.id,
                job_id=job.id,
                author_id=author_id,
                content=rng.choice(CUSTOMER_NOTES),
                visibility=NoteVisibility.CUSTOMER_VISIBLE,
            )
        )
        notes += 1
        # Not every job gets an internal remark; the ones that do prove the
        # visibility split in the demo.
        if rng.random() < 0.6:
            db.add(
                JobNote(
                    organization_id=org.id,
                    job_id=job.id,
                    author_id=author_id,
                    content=rng.choice(INTERNAL_NOTES),
                    visibility=NoteVisibility.INTERNAL,
                )
            )
            notes += 1
    db.flush()

    photos = _seed_photos(db, org, completed[:JOBS_WITH_PHOTOS])
    logger.info("seeded job content", extra={"notes": notes, "photos": photos})
    return {"notes": notes, "photos": photos}


def _seed_photos(db: Session, org: Organization, jobs: list[Job]) -> int:
    """Upload real objects, or skip cleanly when storage is unavailable."""
    storage = get_object_storage()
    try:
        storage.ensure_bucket()
    except Exception:
        logger.warning("object storage unreachable; skipping demo photos")
        return 0

    created = 0
    for job in jobs:
        uploader_id = db.scalar(select(Employee.user_id).where(Employee.id == job.employee_id))
        if uploader_id is None:
            continue
        for photo_type in (PhotoType.BEFORE, PhotoType.AFTER):
            key = storage.build_key(organization_id=org.id, job_id=job.id, mime_type="image/png")
            try:
                storage.put(key=key, body=SAMPLE_PNG, mime_type="image/png")
            except Exception:
                logger.warning("failed to upload a demo photo; skipping the rest")
                return created
            db.add(
                JobPhoto(
                    organization_id=org.id,
                    job_id=job.id,
                    uploaded_by=uploader_id,
                    photo_type=photo_type,
                    storage_key=key,
                    mime_type="image/png",
                    file_size=len(SAMPLE_PNG),
                )
            )
            created += 1
    db.flush()
    return created


def seed_notifications(db: Session, org: Organization) -> int:
    """A short history for the demo customer, with the most recent unread."""
    if db.scalar(
        select(func.count()).select_from(Notification).where(Notification.organization_id == org.id)
    ):
        return 0

    demo_customer = db.scalar(
        select(Customer)
        .where(Customer.organization_id == org.id)
        .where(Customer.user.has(email="customer@serviceflow.demo"))
    )
    if demo_customer is None:
        return 0

    recent = list(
        db.scalars(
            select(Job)
            .join(Job.booking)
            .where(Job.organization_id == org.id)
            .where(Job.booking.has(customer_id=demo_customer.id))
            .order_by(Job.scheduled_start.desc())
            .limit(4)
        )
    )

    created = 0
    for index, job in enumerate(recent):
        booking = job.booking
        finished = job.status is JobStatus.COMPLETED
        db.add(
            Notification(
                organization_id=org.id,
                user_id=demo_customer.user_id,
                type=(
                    NotificationType.JOB_COMPLETED
                    if finished
                    else NotificationType.BOOKING_CONFIRMED
                ),
                subject=(
                    f"Your {booking.service.name} is finished"
                    if finished
                    else f"Your {booking.service.name} is confirmed"
                ),
                body=(
                    f"{booking.vehicle.display_name} is ready. "
                    "Open the booking to see photos and notes from the visit."
                    if finished
                    else f"{job.employee.user.full_name} will take care of it."
                ),
                # Leave the newest two unread so the badge is visible in the demo.
                status=NotificationStatus.PENDING if index < 2 else NotificationStatus.READ,
                payload={"booking_id": str(booking.id), "job_id": str(job.id)},
            )
        )
        created += 1

    db.flush()
    logger.info("seeded notifications", extra={"notifications": created})
    return created
