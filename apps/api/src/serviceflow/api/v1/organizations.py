"""Organization reads and settings, always scoped to the caller's verified membership."""

from __future__ import annotations

from fastapi import APIRouter

from serviceflow.api.deps import ActiveUser, DbSession, OrganizationManager
from serviceflow.core.errors import NotFound
from serviceflow.db.models.enums import AuditAction
from serviceflow.db.models.organization import Organization
from serviceflow.schemas.envelope import DataResponse
from serviceflow.schemas.organization import OrganizationRead, OrganizationUpdate
from serviceflow.services import audit

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


@router.patch(
    "/current",
    response_model=DataResponse[OrganizationRead],
    summary="Update business settings (owners only)",
)
def update_organization(
    payload: OrganizationUpdate, current_user: OrganizationManager, db: DbSession
) -> DataResponse[OrganizationRead]:
    organization = db.get(Organization, current_user.organization_id)
    if organization is None:
        raise NotFound("That organization no longer exists.")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(organization, field, str(value) if field == "email" else value)
    audit.record(
        db,
        organization_id=organization.id,
        actor_user_id=current_user.user_id,
        action=AuditAction.ORGANIZATION_UPDATED,
        resource_type="organization",
        resource_id=organization.id,
        metadata={"fields": ", ".join(sorted(changes)) or "none"},
    )
    db.commit()
    db.refresh(organization)
    return DataResponse[OrganizationRead](data=OrganizationRead.model_validate(organization))
