"""The caller's own in-app notifications (PRD 16)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from serviceflow.api.deps import ActiveUser, DbSession
from serviceflow.core.pagination import Pagination
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.schemas.notification import MarkAllReadResult, NotificationRead, UnreadCount
from serviceflow.services import notifications as notifications_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=PagedResponse[NotificationRead], summary="Your notifications")
def list_notifications(
    current_user: ActiveUser,
    db: DbSession,
    pagination: Pagination,
    unread_only: Annotated[bool, Query()] = False,
) -> PagedResponse[NotificationRead]:
    page = notifications_service.list_notifications(
        db,
        current_user.organization_id,
        current_user.user_id,
        pagination=pagination,
        unread_only=unread_only,
    )
    return paged(
        [NotificationRead.from_model(row) for row in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/unread-count", response_model=DataResponse[UnreadCount], summary="Unread badge")
def unread_count(current_user: ActiveUser, db: DbSession) -> DataResponse[UnreadCount]:
    count = notifications_service.unread_count(
        db, current_user.organization_id, current_user.user_id
    )
    return DataResponse[UnreadCount](data=UnreadCount(unread=count))


@router.post(
    "/{notification_id}/read",
    response_model=DataResponse[NotificationRead],
    summary="Mark one read",
)
def mark_read(
    notification_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[NotificationRead]:
    notification = notifications_service.mark_read(
        db, current_user.organization_id, current_user.user_id, notification_id
    )
    return DataResponse[NotificationRead](data=NotificationRead.from_model(notification))


@router.post("/read-all", response_model=DataResponse[MarkAllReadResult], summary="Mark all read")
def mark_all_read(current_user: ActiveUser, db: DbSession) -> DataResponse[MarkAllReadResult]:
    marked = notifications_service.mark_all_read(
        db, current_user.organization_id, current_user.user_id
    )
    return DataResponse[MarkAllReadResult](data=MarkAllReadResult(marked=marked))
