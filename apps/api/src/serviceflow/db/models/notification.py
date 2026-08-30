from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.enums import NotificationChannel, NotificationStatus, NotificationType
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.user import User


class Notification(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """A message for one user (PRD 7, 16).

    Rows are written inside the transaction of the event they describe, so a
    rolled-back booking cannot leave a notification claiming it was confirmed.

    `channel` already carries EMAIL alongside IN_APP: phase 5 only writes IN_APP
    rows, and phase 6 adds an EMAIL row per event plus a worker that moves it from
    PENDING to SENT. `sent_at` and `failed_at` exist now so that worker needs no
    migration.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_user_id_status", "user_id", "status"),
        Index("ix_notifications_organization_id_created_at", "organization_id", "created_at"),
        # Serves the unread badge, which is the most frequent read of this table.
        Index(
            "ix_notifications_unread",
            "user_id",
            "channel",
            postgresql_where=("status = 'PENDING'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notification_type", native_enum=True), nullable=False
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel", native_enum=True),
        nullable=False,
        default=NotificationChannel.IN_APP,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", native_enum=True),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Deep-link target, e.g. {"booking_id": "..."}. Never contains internal notes.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def unread(self) -> bool:
        """In-app rows land PENDING and become READ when the user opens them."""
        return self.status is NotificationStatus.PENDING
