"""The admin activity feed (PRD 35).

Read-only by construction: there is no route here that writes, updates or
deletes an audit entry, and the table rejects both at the database level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from serviceflow.api.deps import AdminUser, DbSession
from serviceflow.core.pagination import Pagination
from serviceflow.db.models.enums import AuditAction
from serviceflow.schemas.audit import AuditActor, AuditEntryRead
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import audit

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=PagedResponse[AuditEntryRead], summary="Activity feed")
def list_activity(
    current_user: AdminUser,
    db: DbSession,
    pagination: Pagination,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    resource_type: Annotated[str | None, Query(max_length=60)] = None,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[datetime | None, Query(description="Inclusive lower bound")] = None,
    until: Annotated[datetime | None, Query(description="Inclusive upper bound")] = None,
    sort: Annotated[str | None, Query(description="created_at | -created_at")] = None,
) -> PagedResponse[AuditEntryRead]:
    page = audit.list_entries(
        db,
        current_user.organization_id,
        pagination=pagination,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        since=since,
        until=until,
        # Newest first unless explicitly asked otherwise.
        ascending=sort == "created_at",
    )
    return paged(
        [AuditEntryRead.from_model(entry) for entry in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/actors", response_model=DataResponse[list[AuditActor]], summary="Actors in the trail")
def list_actors(current_user: AdminUser, db: DbSession) -> DataResponse[list[AuditActor]]:
    rows = audit.distinct_actors(db, current_user.organization_id)
    return DataResponse[list[AuditActor]](
        data=[AuditActor(id=actor_id, full_name=name) for actor_id, name in rows]
    )
