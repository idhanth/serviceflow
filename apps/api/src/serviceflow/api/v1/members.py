"""Who belongs to this business, with which role. Owners manage; readers list."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import DbSession, MembersManager, MembersReader
from serviceflow.core.pagination import Pagination
from serviceflow.db.models.enums import Role
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.schemas.admin import MemberInvite, MemberRead, MemberUpdate
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import members as members_service

router = APIRouter(prefix="/members", tags=["members"])


def _read(membership: OrganizationMembership) -> MemberRead:
    user = membership.user
    return MemberRead(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        status=membership.status,
        can_sign_in=user.password_hash is not None,
        created_at=membership.created_at,
    )


@router.get("", response_model=PagedResponse[MemberRead], summary="List members")
def list_members(
    current_user: MembersReader,
    db: DbSession,
    pagination: Pagination,
    role: Annotated[Role | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> PagedResponse[MemberRead]:
    page = members_service.list_members(
        db, current_user.organization_id, pagination=pagination, role=role, q=q
    )
    return paged(
        [_read(m) for m in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.post(
    "",
    response_model=DataResponse[MemberRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a member with a role",
)
def invite_member(
    payload: MemberInvite, current_user: MembersManager, db: DbSession
) -> DataResponse[MemberRead]:
    membership = members_service.invite_member(
        db,
        current_user.organization_id,
        actor_user_id=current_user.user_id,
        email=str(payload.email),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        job_title=payload.job_title,
    )
    return DataResponse[MemberRead](data=_read(membership))


@router.patch(
    "/{membership_id}", response_model=DataResponse[MemberRead], summary="Change role or status"
)
def update_member(
    membership_id: uuid.UUID, payload: MemberUpdate, current_user: MembersManager, db: DbSession
) -> DataResponse[MemberRead]:
    membership = members_service.update_member(
        db,
        current_user.organization_id,
        membership_id,
        actor_user_id=current_user.user_id,
        role=payload.role,
        status=payload.status,
    )
    return DataResponse[MemberRead](data=_read(membership))
