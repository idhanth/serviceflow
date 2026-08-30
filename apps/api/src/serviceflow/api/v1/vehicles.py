"""Vehicle endpoints.

Shared by admins (org-wide) and customers (their own only). The scoping decision
lives in the service layer so no route can accidentally widen it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import ActiveUser, DbSession
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.db.models.enums import Role
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate
from serviceflow.services import vehicles as vehicles_service

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=PagedResponse[VehicleRead], summary="List vehicles")
def list_vehicles(
    current_user: ActiveUser,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[
        str | None, Query(max_length=120, description="Make, model, color or plate")
    ] = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    sort: Annotated[str | None, Query(description="created_at | make | year")] = None,
) -> PagedResponse[VehicleRead]:
    is_admin = current_user.has_role(Role.ADMIN)
    page = vehicles_service.list_vehicles(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        pagination=pagination,
        q=q,
        customer_id=customer_id,
        sort=parse_sort(sort, allowed=vehicles_service.VEHICLE_SORTS, default="-created_at"),
    )
    return paged(
        [VehicleRead.from_model(vehicle, include_owner=is_admin) for vehicle in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{vehicle_id}", response_model=DataResponse[VehicleRead], summary="Get a vehicle")
def get_vehicle(
    vehicle_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[VehicleRead]:
    vehicle = vehicles_service.get_vehicle(
        db,
        current_user.organization_id,
        vehicle_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[VehicleRead](
        data=VehicleRead.from_model(vehicle, include_owner=current_user.has_role(Role.ADMIN))
    )


@router.post(
    "",
    response_model=DataResponse[VehicleRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a vehicle",
)
def create_vehicle(
    payload: VehicleCreate, current_user: ActiveUser, db: DbSession
) -> DataResponse[VehicleRead]:
    vehicle = vehicles_service.create_vehicle(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        customer_id=payload.customer_id,
        year=payload.year,
        make=payload.make,
        model=payload.model,
        color=payload.color,
        license_plate=payload.license_plate,
        notes=payload.notes,
    )
    return DataResponse[VehicleRead](
        data=VehicleRead.from_model(vehicle, include_owner=current_user.has_role(Role.ADMIN))
    )


@router.patch("/{vehicle_id}", response_model=DataResponse[VehicleRead], summary="Update a vehicle")
def update_vehicle(
    vehicle_id: uuid.UUID, payload: VehicleUpdate, current_user: ActiveUser, db: DbSession
) -> DataResponse[VehicleRead]:
    vehicle = vehicles_service.update_vehicle(
        db,
        current_user.organization_id,
        vehicle_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return DataResponse[VehicleRead](
        data=VehicleRead.from_model(vehicle, include_owner=current_user.has_role(Role.ADMIN))
    )


@router.delete(
    "/{vehicle_id}",
    response_model=DataResponse[VehicleRead],
    summary="Archive a vehicle (soft delete)",
)
def archive_vehicle(
    vehicle_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[VehicleRead]:
    """Archives rather than deletes: bookings and jobs reference vehicles."""
    vehicle = vehicles_service.archive_vehicle(
        db,
        current_user.organization_id,
        vehicle_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[VehicleRead](
        data=VehicleRead.from_model(vehicle, include_owner=current_user.has_role(Role.ADMIN))
    )
