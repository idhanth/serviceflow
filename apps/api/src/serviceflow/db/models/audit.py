from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, UUIDPrimaryKey
from serviceflow.db.models.enums import AuditAction
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.user import User


class AuditLog(UUIDPrimaryKey, OrganizationScoped, Base):
    """An immutable record of who changed what (PRD 7, 35).

    Deliberately no `Timestamps` mixin: an audit row has a `created_at` and no
    `updated_at`, because it is never updated. A database trigger enforces that
    (see the phase 7 migration) - immutability here is not a UI convention.

    `metadata_` holds a small, deliberately-chosen summary of the change. It must
    never carry secrets, tokens, presigned URLs or the content of internal notes;
    `services/audit.py` is the only place that builds it, so there is exactly one
    place to check that rule.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_audit_logs_organization_id_action", "organization_id", "action"),
        Index("ix_audit_logs_resource", "organization_id", "resource_type", "resource_id"),
        Index("ix_audit_logs_actor", "organization_id", "actor_user_id"),
    )

    # RESTRICT: a trail that can lose its actor is not a trail. Nothing in the
    # application deletes users; this guards a future mistake.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action", native_enum=True), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # "metadata" is reserved on the declarative base, hence the trailing underscore.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped[User | None] = relationship(lazy="joined")
