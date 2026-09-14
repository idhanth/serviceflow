"""Platform administration: businesses on the platform, never their records."""

from __future__ import annotations

from fastapi import APIRouter, status

from serviceflow.api.deps import DbSession, PlatformAdmin
from serviceflow.schemas.admin import TenantCreate, TenantSummary
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services import platform as platform_service

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get(
    "/tenants",
    response_model=DataResponse[list[TenantSummary]],
    summary="Businesses on the platform",
)
def list_tenants(current_user: PlatformAdmin, db: DbSession) -> DataResponse[list[TenantSummary]]:
    return DataResponse[list[TenantSummary]](data=platform_service.list_tenants(db))


@router.post(
    "/tenants",
    response_model=DataResponse[TenantSummary],
    status_code=status.HTTP_201_CREATED,
    summary="Create a business and its first owner",
)
def create_tenant(
    payload: TenantCreate, current_user: PlatformAdmin, db: DbSession
) -> DataResponse[TenantSummary]:
    organization = platform_service.create_tenant(db, payload, actor_user_id=current_user.user_id)
    summary = next(t for t in platform_service.list_tenants(db) if t.id == organization.id)
    return DataResponse[TenantSummary](data=summary)
