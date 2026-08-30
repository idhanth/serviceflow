"""Service catalog endpoints.

Everyone in the organization can read the catalog - customers need it to book -
but only admins may change it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import ActiveUser, AdminUser, DbSession
from serviceflow.core.errors import NotFound
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.db.models.enums import Role
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate
from serviceflow.services import catalog

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=PagedResponse[ServiceRead], summary="List services")
def list_services(
    current_user: ActiveUser,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[str | None, Query(max_length=120, description="Name or description")] = None,
    active: Annotated[bool | None, Query()] = None,
    sort: Annotated[str | None, Query(description="name | price | duration | created_at")] = None,
) -> PagedResponse[ServiceRead]:
    # Non-admins never see retired offerings: their `active` filter is ignored
    # rather than honoured, so no query path can surface a retired service.
    effective_active = active if current_user.has_role(Role.ADMIN) else True
    page = catalog.list_services(
        db,
        current_user.organization_id,
        pagination=pagination,
        q=q,
        active=effective_active,
        sort=parse_sort(sort, allowed=catalog.SERVICE_SORTS, default="name"),
    )
    return paged(
        [ServiceRead.from_model(service) for service in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{service_id}", response_model=DataResponse[ServiceRead], summary="Get a service")
def get_service(
    service_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[ServiceRead]:
    service = catalog.get_service(db, current_user.organization_id, service_id)
    if not service.active and not current_user.has_role(Role.ADMIN):
        raise NotFound("We couldn't find that service.")
    return DataResponse[ServiceRead](data=ServiceRead.from_model(service))


@router.post(
    "",
    response_model=DataResponse[ServiceRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a service",
)
def create_service(
    payload: ServiceCreate, current_user: AdminUser, db: DbSession
) -> DataResponse[ServiceRead]:
    service = catalog.create_service(
        db,
        current_user.organization_id,
        name=payload.name,
        description=payload.description,
        base_price=payload.base_price,
        duration_minutes=payload.duration_minutes,
        image_url=payload.image_url,
        actor_user_id=current_user.user_id,
    )
    return DataResponse[ServiceRead](data=ServiceRead.from_model(service))


@router.patch("/{service_id}", response_model=DataResponse[ServiceRead], summary="Update a service")
def update_service(
    service_id: uuid.UUID, payload: ServiceUpdate, current_user: AdminUser, db: DbSession
) -> DataResponse[ServiceRead]:
    service = catalog.update_service(
        db,
        current_user.organization_id,
        service_id,
        changes=payload.model_dump(exclude_unset=True),
        actor_user_id=current_user.user_id,
    )
    return DataResponse[ServiceRead](data=ServiceRead.from_model(service))


@router.delete(
    "/{service_id}",
    response_model=DataResponse[ServiceRead],
    summary="Retire a service (soft delete)",
)
def deactivate_service(
    service_id: uuid.UUID, current_user: AdminUser, db: DbSession
) -> DataResponse[ServiceRead]:
    """Deactivates rather than deletes: bookings and jobs will reference services."""
    service = catalog.deactivate_service(
        db, current_user.organization_id, service_id, actor_user_id=current_user.user_id
    )
    return DataResponse[ServiceRead](data=ServiceRead.from_model(service))
