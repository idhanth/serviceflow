"""The operations dashboard for staff with tenant-wide read access."""

from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.deps import DashboardReader, DbSession
from serviceflow.schemas.admin import DashboardRead
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services.dashboard import build_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DataResponse[DashboardRead], summary="Today at a glance")
def dashboard(current_user: DashboardReader, db: DbSession) -> DataResponse[DashboardRead]:
    return DataResponse[DashboardRead](data=build_dashboard(db, current_user.organization_id))
