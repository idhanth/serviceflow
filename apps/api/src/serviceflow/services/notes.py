"""Job notes, and the visibility boundary that keeps internal remarks internal.

The rule that matters (PRD 6, 7): a customer must never receive an INTERNAL note
through any path. That is enforced in one place - `list_notes` filters by
audience, and `get_note` refuses a customer an internal row - so no serializer or
route can leak one by forgetting.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from serviceflow.auth.permissions import Permission as P
from serviceflow.auth.permissions import can
from serviceflow.core.errors import Forbidden, InvalidRole, NotFound, ValidationFailed
from serviceflow.db.models.enums import AuditAction, NoteVisibility, Role
from serviceflow.db.models.job_note import JobNote
from serviceflow.services import audit
from serviceflow.services.jobs import JobAudience, resolve_job_for_viewer

logger = logging.getLogger(__name__)

MAX_NOTE_LENGTH = 4000


def list_notes(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> list[JobNote]:
    _, audience = resolve_job_for_viewer(db, organization_id, job_id, roles=roles, user_id=user_id)

    filters = [JobNote.organization_id == organization_id, JobNote.job_id == job_id]
    if audience is JobAudience.CUSTOMER:
        # The single place a customer's note query is narrowed.
        filters.append(JobNote.visibility == NoteVisibility.CUSTOMER_VISIBLE)

    return list(
        db.scalars(
            select(JobNote)
            .where(*filters)
            .options(joinedload(JobNote.author))
            .order_by(JobNote.created_at.desc())
        ).unique()
    )


def get_note(
    db: Session,
    organization_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> tuple[JobNote, JobAudience]:
    note = db.scalar(
        select(JobNote)
        .where(JobNote.id == note_id, JobNote.organization_id == organization_id)
        .options(joinedload(JobNote.author))
    )
    if note is None:
        raise NotFound("We couldn't find that note.")

    # Reaching the note requires reaching its job first, which is where tenancy,
    # assignment and customer ownership are all decided.
    _, audience = resolve_job_for_viewer(
        db, organization_id, note.job_id, roles=roles, user_id=user_id
    )
    if audience is JobAudience.CUSTOMER and not note.customer_visible:
        # Indistinguishable from a note that does not exist.
        raise NotFound("We couldn't find that note.")
    return note, audience


def create_note(
    db: Session,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    content: str,
    visibility: NoteVisibility,
) -> JobNote:
    """Only staff write notes; customers read the ones marked for them."""
    _, audience = resolve_job_for_viewer(db, organization_id, job_id, roles=roles, user_id=user_id)
    if audience is not JobAudience.STAFF:
        raise InvalidRole("Only the team can add notes to a job.")

    body = content.strip()
    if not body:
        raise ValidationFailed(
            "Write something before saving.", details={"fields": {"content": "Required."}}
        )
    if len(body) > MAX_NOTE_LENGTH:
        raise ValidationFailed(
            "That note is too long.",
            details={"fields": {"content": f"Keep it under {MAX_NOTE_LENGTH} characters."}},
        )

    note = JobNote(
        organization_id=organization_id,
        job_id=job_id,
        author_id=user_id,
        content=body,
        visibility=visibility,
    )
    db.add(note)
    db.flush()
    # The note's text is deliberately not recorded: an internal note must not be
    # copied into a table with no delete.
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.NOTE_ADDED,
        resource_type="job",
        resource_id=job_id,
        metadata={"visibility": visibility.value},
    )
    db.commit()
    db.refresh(note)
    logger.info("job note created", extra={"job_id": str(job_id), "visibility": visibility.value})
    return note


def delete_note(
    db: Session,
    organization_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> None:
    """An author may remove their own note; a dispatcher may remove any in the org."""
    note, audience = get_note(db, organization_id, note_id, roles=roles, user_id=user_id)
    if audience is JobAudience.CUSTOMER:
        raise NotFound("We couldn't find that note.")
    if audience is JobAudience.READER:
        raise InvalidRole("Read-only access can't remove notes.")
    if not can(roles, P.JOBS_DISPATCH) and note.author_id != user_id:
        raise Forbidden("You can only remove notes you wrote.")

    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=user_id,
        action=AuditAction.NOTE_DELETED,
        resource_type="job",
        resource_id=note.job_id,
        metadata={"visibility": note.visibility.value},
    )
    db.delete(note)
    db.commit()
