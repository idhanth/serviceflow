from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.enums import AuditAction


class AuditEntryRead(BaseModel):
    id: uuid.UUID
    action: AuditAction
    actor_name: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, entry: AuditLog) -> AuditEntryRead:
        return cls(
            id=entry.id,
            action=entry.action,
            # A deleted actor would otherwise render as blank; the FK makes this
            # unreachable today, and it stays readable if that ever changes.
            actor_name=entry.actor.full_name if entry.actor else "System",
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            metadata=entry.metadata_,
            created_at=entry.created_at,
        )


class AuditActor(BaseModel):
    id: uuid.UUID
    full_name: str
