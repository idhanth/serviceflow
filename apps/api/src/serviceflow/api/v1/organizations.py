"""Organization reads, always scoped to the caller's verified membership."""

from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.deps import ActiveUser, DbSession
from serviceflow.core.errors import NotFound
from serviceflow.db.models.organization import Organization
from serviceflow.schemas.envelope import DataResponse
from serviceflow.schemas.organization import OrganizationRead

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get(
    "/current",
    response_model=DataResponse[OrganizationRead],
    summary="The organization this request is scoped to",
)
def current_organization(current_user: ActiveUser, db: DbSession) -> DataResponse[OrganizationRead]:
    organization = db.get(Organization, current_user.organization_id)
    if organization is None:
        raise NotFound("That organization no longer exists.")
    return DataResponse[OrganizationRead](data=OrganizationRead.model_validate(organization))
