from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

MAX_KEY_LENGTH = 200
MIN_KEY_LENGTH = 8


class IdempotencyRecord(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """One booking-creation attempt, keyed by the client's Idempotency-Key (PRD 14).

    The unique constraint on (organization_id, user_id, key) is the guarantee:
    two concurrent requests carrying the same key cannot both insert, so exactly
    one proceeds to create the booking and the other is told to wait for - or
    replay - its result. Scoping by organization *and* user means the same string
    used by two different people never collides.

    A row is inserted *before* the booking is created and completed afterwards,
    inside the same transaction. A rolled-back booking therefore takes its
    idempotency record with it, and can never leave a record claiming success.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "key", name="one_record_per_key"),
        CheckConstraint(
            f"length(key) BETWEEN {MIN_KEY_LENGTH} AND {MAX_KEY_LENGTH}", name="key_length"
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), nullable=False)
    # Endpoint identity, so one key reused across different operations is not
    # mistaken for a retry of this one.
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    # SHA-256 of the normalised request body. A retry with different content is a
    # conflict, not a replay.
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def completed(self) -> bool:
        return self.resource_id is not None
