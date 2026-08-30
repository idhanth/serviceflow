from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from serviceflow.db.models.enums import NotificationType
from serviceflow.db.models.notification import Notification


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: NotificationType
    subject: str
    body: str
    unread: bool
    payload: dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, notification: Notification) -> NotificationRead:
        return cls(
            id=notification.id,
            type=notification.type,
            subject=notification.subject,
            body=notification.body,
            unread=notification.unread,
            payload=notification.payload,
            created_at=notification.created_at,
        )


class UnreadCount(BaseModel):
    unread: int


class MarkAllReadResult(BaseModel):
    marked: int
