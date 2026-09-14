"""Job photos: presigned upload, verified finalize, presigned read, delete.

The flow (PRD 15):

    1. staff asks for an upload slot     -> POST /jobs/{id}/photos/presign
    2. the API authorizes and validates, mints a server-side key, and returns a
       presigned POST whose policy pins the content type and a 10 MB ceiling
    3. the browser uploads straight to object storage
    4. the client finalizes               -> POST /jobs/{id}/photos
    5. the API HEADs the object and only then writes a JobPhoto row

Step 5 is what makes the metadata trustworthy: a client that skips the upload, or
uploads something other than it declared, cannot produce a row. Nothing is
persisted on the strength of a client's word.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from serviceflow.auth.permissions import Permission as P
from serviceflow.auth.permissions import can
from serviceflow.core.errors import InvalidRole, NotFound, UploadFailed, ValidationFailed
from serviceflow.db.models.enums import AuditAction, JobStatus, PhotoType, Role
from serviceflow.db.models.job_photo import MAX_PHOTO_BYTES, MAX_PHOTOS_PER_JOB, JobPhoto
from serviceflow.services import audit
from serviceflow.services.jobs import JobAudience, resolve_job_for_viewer
from serviceflow.services.storage import ALLOWED_MIME_TYPES, PresignedUpload, get_object_storage

logger = logging.getLogger(__name__)

# Photos may be added while there is still work to record against.
UPLOADABLE_STATES = frozenset({JobStatus.SCHEDULED, JobStatus.IN_PROGRESS, JobStatus.COMPLETED})
# Once the job is closed out, the record is fixed.
DELETABLE_STATES = frozenset({JobStatus.SCHEDULED, JobStatus.IN_PROGRESS})


@dataclass(frozen=True, slots=True)
class PhotoView:
    """A photo plus a short-lived URL to fetch it. The bucket stays private."""

    photo: JobPhoto
    url: str


def _require_staff(db: Session, organization_id: uuid.UUID, job_id: uuid.UUID, *, roles, user_id):  # type: ignore[no-untyped-def]
    job, audience = resolve_job_for_viewer(
        db, organization_id, job_id, roles=roles, user_id=user_id
    )
    if audience is not JobAudience.STAFF:
        raise InvalidRole("Only the team can change a job's photos.")
    return job


def _count(db: Session, job_id: uuid.UUID) -> int:
    return (
        db.scalar(select(func.count()).select_from(JobPhoto).where(JobPhoto.job_id == job_id)) or 0
    )


def list_photos(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> list[PhotoView]:
    """Every photo on the job, for staff and for its own customer alike.

    JobPhoto has no visibility column: a job's photos are the record of work on
    that customer's property, so its customer may see all of them (docs/adr-0005).
    Anything not for the customer belongs in an INTERNAL note.
    """
    resolve_job_for_viewer(db, organization_id, job_id, roles=roles, user_id=user_id)

    storage = get_object_storage()
    photos = db.scalars(
        select(JobPhoto)
        .where(JobPhoto.organization_id == organization_id, JobPhoto.job_id == job_id)
        .options(joinedload(JobPhoto.uploader))
        .order_by(JobPhoto.photo_type, JobPhoto.created_at)
    ).unique()
    return [
        PhotoView(photo=photo, url=storage.presign_download(photo.storage_key)) for photo in photos
    ]


def presign_upload(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    mime_type: str,
    file_size: int,
) -> PresignedUpload:
    """Authorize, validate, then mint a narrowly-scoped upload slot.

    Everything checked here is checked again at finalize against what was really
    stored, because a presigned POST is handed to a browser we do not control.
    """
    job = _require_staff(db, organization_id, job_id, roles=roles, user_id=user_id)

    if job.status not in UPLOADABLE_STATES:
        raise ValidationFailed(
            "Photos can't be added to a cancelled job.",
            details={"fields": {"job": "Job is not accepting photos."}},
        )
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValidationFailed(
            "Only JPEG, PNG and WebP images can be uploaded.",
            details={"fields": {"mime_type": "Unsupported file type."}},
        )
    if file_size <= 0 or file_size > MAX_PHOTO_BYTES:
        raise ValidationFailed(
            "Photos must be smaller than 10 MB.",
            details={"fields": {"file_size": f"Maximum {MAX_PHOTO_BYTES} bytes."}},
        )
    if _count(db, job_id) >= MAX_PHOTOS_PER_JOB:
        raise ValidationFailed(
            f"This job already has the maximum of {MAX_PHOTOS_PER_JOB} photos.",
            details={"fields": {"photos": "Limit reached."}},
        )

    storage = get_object_storage()
    key = storage.build_key(organization_id=organization_id, job_id=job_id, mime_type=mime_type)
    return storage.presign_upload(key=key, mime_type=mime_type, max_bytes=MAX_PHOTO_BYTES)


def finalize_upload(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    storage_key: str,
    photo_type: PhotoType,
) -> PhotoView:
    """Persist metadata only after confirming the object is really there."""
    _require_staff(db, organization_id, job_id, roles=roles, user_id=user_id)
    storage = get_object_storage()

    # A client could return any string here, so the key must be re-checked
    # against the scope it could only have been minted for.
    if not storage.owns_key(storage_key, organization_id=organization_id, job_id=job_id):
        logger.warning("rejected foreign storage key", extra={"job_id": str(job_id)})
        raise ValidationFailed(
            "That upload doesn't belong to this job.",
            details={"fields": {"storage_key": "Invalid."}},
        )

    stored = storage.head(storage_key)
    if stored is None:
        # The upload never landed - do not record a photo that does not exist.
        raise UploadFailed("That upload didn't complete. Please try again.")

    if stored.content_type not in ALLOWED_MIME_TYPES:
        storage.delete(storage_key)
        raise ValidationFailed(
            "Only JPEG, PNG and WebP images can be uploaded.",
            details={"fields": {"mime_type": "Unsupported file type."}},
        )
    if stored.size <= 0 or stored.size > MAX_PHOTO_BYTES:
        storage.delete(storage_key)
        raise ValidationFailed(
            "Photos must be smaller than 10 MB.",
            details={"fields": {"file_size": "Too large."}},
        )

    # Re-checked here rather than only at presign: twelve slots could have been
    # handed out concurrently.
    if _count(db, job_id) >= MAX_PHOTOS_PER_JOB:
        storage.delete(storage_key)
        raise ValidationFailed(
            f"This job already has the maximum of {MAX_PHOTOS_PER_JOB} photos.",
            details={"fields": {"photos": "Limit reached."}},
        )

    photo = JobPhoto(
        organization_id=organization_id,
        job_id=job_id,
        uploaded_by=user_id,
        photo_type=photo_type,
        storage_key=storage_key,
        mime_type=stored.content_type,
        file_size=stored.size,
    )
    db.add(photo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The same key finalized twice; the object is already accounted for.
        raise ValidationFailed("That photo has already been saved.") from exc

    db.refresh(photo)
    logger.info(
        "job photo stored",
        extra={"job_id": str(job_id), "bytes": stored.size, "photo_type": photo_type.value},
    )
    return PhotoView(photo=photo, url=storage.presign_download(photo.storage_key))


def delete_photo(
    db: Session,
    organization_id: uuid.UUID,
    photo_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> None:
    """Remove the row and the object together.

    The row goes first: if the object delete then fails, the result is an
    unreferenced object a lifecycle rule can sweep, which is far better than a
    row pointing at bytes that are gone.
    """
    photo = db.scalar(
        select(JobPhoto).where(JobPhoto.id == photo_id, JobPhoto.organization_id == organization_id)
    )
    if photo is None:
        raise NotFound("We couldn't find that photo.")

    job = _require_staff(db, organization_id, photo.job_id, roles=roles, user_id=user_id)
    if job.status not in DELETABLE_STATES and not can(roles, P.JOBS_DISPATCH):
        raise ValidationFailed(
            "This job is closed out, so its photos can't be removed.",
            details={"fields": {"job": "Job is complete."}},
        )

    key = photo.storage_key
    # The storage key is not recorded: it is the address of a private object.
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.PHOTO_DELETED,
        resource_type="job",
        resource_id=photo.job_id,
        metadata={"photo_type": photo.photo_type.value},
    )
    db.delete(photo)
    db.commit()

    try:
        get_object_storage().delete(key)
    except Exception:
        logger.exception("orphaned object left in storage", extra={"storage_key": key})
