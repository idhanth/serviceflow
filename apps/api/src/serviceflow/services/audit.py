"""The audit trail (PRD 35).

Rows are *staged* on the caller's session and never committed here - the same
pattern notifications use. A committed action leaves an audit row; a rolled-back
one leaves nothing claiming it happened. Nothing in this module calls `commit()`.

This is also the only place audit metadata is constructed, which gives one place
to enforce the rule that it never carries secrets, tokens, presigned URLs or the
text of internal notes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.enums import AuditAction
from serviceflow.db.models.user import User

logger = logging.getLogger(__name__)

# Anything whose name looks like a credential is dropped rather than recorded.
_FORBIDDEN_HINTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "signature",
    "api_key",
    "apikey",
    "cookie",
    "credential",
    "x-amz",
)
MAX_VALUE_LENGTH = 200


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop anything credential-shaped and truncate long values.

    A backstop, not the primary control: call sites are expected to pass only
    what they mean to record. This stops one careless call from writing a secret
    into a table that cannot be edited afterwards.
    """
    if not metadata:
        return None

    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(hint in key.lower() for hint in _FORBIDDEN_HINTS):
            continue
        if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
            value = value[:MAX_VALUE_LENGTH] + "…"
        cleaned[key] = value
    return cleaned or None


def record(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: AuditAction,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Stage one audit row on the caller's transaction.

    `actor_user_id` and `organization_id` come from the authenticated principal
    at the call site - never from a request body, so a client cannot attribute an
    action to someone else or to another tenant.
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_=_safe_metadata(metadata),
    )
    db.add(entry)
    return entry


# ------------------------------------------------------------------ reading


def list_entries(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    actor_user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    ascending: bool = False,
) -> Page[AuditLog]:
    """The activity feed, always pinned to one organization (PRD 35)."""
    filters = [AuditLog.organization_id == organization_id]
    if actor_user_id is not None:
        filters.append(AuditLog.actor_user_id == actor_user_id)
    if action is not None:
        filters.append(AuditLog.action == action)
    if resource_type is not None:
        filters.append(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        filters.append(AuditLog.resource_id == resource_id)
    if since is not None:
        filters.append(AuditLog.created_at >= since)
    if until is not None:
        filters.append(AuditLog.created_at <= until)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    order = AuditLog.created_at.asc() if ascending else AuditLog.created_at.desc()
    items = list(
        db.scalars(
            select(AuditLog)
            .where(*filters)
            .options(joinedload(AuditLog.actor))
            .order_by(order, AuditLog.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def distinct_actors(db: Session, organization_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """Actors who appear in this organization's trail, for the filter control."""
    rows = db.execute(
        select(AuditLog.actor_user_id, User.first_name, User.last_name)
        .join(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.organization_id == organization_id)
        .distinct()
        .order_by(User.first_name, User.last_name)
    ).all()
    return [(row[0], f"{row[1]} {row[2]}") for row in rows]
