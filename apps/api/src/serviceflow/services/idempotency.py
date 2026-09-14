"""Idempotent booking creation (PRD 14).

The guarantee is a database uniqueness constraint, not a cache:
`(organization_id, user_id, key)` is unique, so two concurrent requests carrying
the same key cannot both insert. One wins and creates the booking; the other
gets a constraint violation, waits for the winner's row and replays its result.
That survives API restarts and works across processes, which an in-memory table
would not.

Ordering matters. The record is inserted and completed **inside the booking's own
transaction**, so:

  * a rolled-back booking takes its idempotency record with it - a record can
    never claim success for work that did not commit;
  * a committed booking always has its record, so the retry replays rather than
    creating a second booking.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from serviceflow.core.errors import IdempotencyConflict, ValidationFailed
from serviceflow.db.models.idempotency import (
    MAX_KEY_LENGTH,
    MIN_KEY_LENGTH,
    IdempotencyRecord,
)
from serviceflow.db.tenancy import allow_cross_tenant

logger = logging.getLogger(__name__)

# Retained long enough to cover any realistic client retry, short enough that the
# table stays small. Expired rows are reusable; a periodic cleanup can delete them.
RETENTION = timedelta(hours=24)

# Printable, URL-safe-ish. Deliberately strict: a key is an opaque token, and
# anything else is a client bug worth reporting rather than silently accepting.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclass(frozen=True, slots=True)
class Replay:
    """A previous result for this key, to be returned instead of re-executing."""

    resource_id: uuid.UUID
    response_status: int
    response_body: dict[str, Any] | None


def validate_key(key: str) -> str:
    key = key.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
        raise ValidationFailed(
            "That idempotency key isn't usable.",
            details={
                "fields": {
                    "Idempotency-Key": (
                        f"Use between {MIN_KEY_LENGTH} and {MAX_KEY_LENGTH} characters."
                    )
                }
            },
        )
    if not _KEY_PATTERN.match(key):
        raise ValidationFailed(
            "That idempotency key isn't usable.",
            details={
                "fields": {
                    "Idempotency-Key": "Use letters, numbers, dot, dash, colon or underscore."
                }
            },
        )
    return key


def fingerprint(payload: dict[str, Any]) -> str:
    """A stable hash of the request, so a changed payload is detectable.

    Sorted keys and a canonical separator mean key order and whitespace do not
    make two identical requests look different.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _live(record: IdempotencyRecord, now: datetime) -> bool:
    return record.expires_at > now


def begin(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    operation: str,
    payload: dict[str, Any],
) -> Replay | None:
    """Claim the key, or return the previous result to replay.

    Returns None when this caller owns the claim and should carry on and do the
    work. The row it inserted is part of the caller's transaction, so it lives or
    dies with the booking.

    Raises IdempotencyConflict when the same key arrives with a different payload,
    or when a competing request holds the claim and has not finished yet.
    """
    key = validate_key(key)
    digest = fingerprint(payload)
    now = datetime.now(UTC)

    existing = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == organization_id,
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.key == key,
        )
    )
    if existing is not None and _live(existing, now):
        return _replay_or_conflict(existing, digest=digest, operation=operation)

    if existing is not None:
        # Expired: the key is free again, so take it over rather than refusing a
        # client that is legitimately reusing an old token.
        db.delete(existing)
        db.flush()

    record = IdempotencyRecord(
        organization_id=organization_id,
        user_id=user_id,
        key=key,
        operation=operation,
        request_fingerprint=digest,
        expires_at=now + RETENTION,
    )
    # A savepoint, so losing the race does not roll back the caller's whole
    # transaction - only this insert attempt.
    savepoint = db.begin_nested()
    db.add(record)
    try:
        # The unique constraint decides the race, not the SELECT above.
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        # Someone else claimed it between the read and the write; their row is
        # authoritative.
        competitor = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
        )
        if competitor is None:  # pragma: no cover - it was just written
            raise
        return _replay_or_conflict(competitor, digest=digest, operation=operation)

    return None


def _replay_or_conflict(record: IdempotencyRecord, *, digest: str, operation: str) -> Replay:
    if record.operation != operation or record.request_fingerprint != digest:
        raise IdempotencyConflict("That idempotency key was already used for a different request.")
    if not record.completed:
        # The original attempt is still running, or died before finishing. Either
        # way, creating a second booking would be exactly the duplicate this
        # exists to prevent.
        raise IdempotencyConflict(
            "That request is already being processed. Please try again in a moment."
        )
    return Replay(
        resource_id=record.resource_id,  # type: ignore[arg-type]
        response_status=record.response_status or 200,
        response_body=record.response_body,
    )


def complete(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    resource_type: str,
    resource_id: uuid.UUID,
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    """Record the outcome. Staged on the caller's transaction, never committed here."""
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == organization_id,
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.key == key.strip(),
        )
    )
    if record is None:  # pragma: no cover - begin() inserted it in this transaction
        return
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.response_status = response_status
    record.response_body = response_body


def purge_expired(db: Session, *, limit: int = 500) -> int:
    """Delete expired records. Safe to run repeatedly; commits its own work."""
    allow_cross_tenant(db)  # expiry is swept across every tenant
    now = datetime.now(UTC)
    stale = list(
        db.scalars(
            select(IdempotencyRecord).where(IdempotencyRecord.expires_at <= now).limit(limit)
        )
    )
    for record in stale:
        db.delete(record)
    if stale:
        db.commit()
    return len(stale)
