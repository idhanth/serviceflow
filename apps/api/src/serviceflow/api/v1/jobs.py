"""Job endpoints.

Employees reach only their own jobs; admins reach all of them. That decision is
made in `services/jobs.py`, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from serviceflow.api.deps import AdminUser, DbSession, EmployeeUser
from serviceflow.core.pagination import Pagination
from serviceflow.db.models.enums import JobStatus, Role
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.schemas.job import JobComplete, JobRead, JobReassign
from serviceflow.services import jobs as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=PagedResponse[JobRead], summary="List jobs")
def list_jobs(
    current_user: EmployeeUser,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    on_date: Annotated[datetime | None, Query(description="Jobs scheduled on this day")] = None,
) -> PagedResponse[JobRead]:
    page = jobs_service.list_jobs(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        pagination=pagination,
        status=status_filter,
        employee_id=employee_id,
        on_date=on_date,
    )
    return paged(
        [JobRead.from_model(job) for job in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{job_id}", response_model=DataResponse[JobRead], summary="Get a job")
def get_job(job_id: uuid.UUID, current_user: EmployeeUser, db: DbSession) -> DataResponse[JobRead]:
    job = jobs_service.get_job(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/start", response_model=DataResponse[JobRead], summary="Start a job")
def start_job(
    job_id: uuid.UUID, current_user: EmployeeUser, db: DbSession
) -> DataResponse[JobRead]:
    job = jobs_service.start_job(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/complete", response_model=DataResponse[JobRead], summary="Complete a job")
def complete_job(
    job_id: uuid.UUID, payload: JobComplete, current_user: EmployeeUser, db: DbSession
) -> DataResponse[JobRead]:
    job = jobs_service.complete_job(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        internal_notes=payload.internal_notes,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/cancel", response_model=DataResponse[JobRead], summary="Cancel a job")
def cancel_job(job_id: uuid.UUID, current_user: AdminUser, db: DbSession) -> DataResponse[JobRead]:
    job = jobs_service.cancel_job(
        db,
        current_user.organization_id,
        job_id,
        roles=frozenset({Role.ADMIN}),
        user_id=current_user.user_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/assign", response_model=DataResponse[JobRead], summary="Reassign a job")
def reassign_job(
    job_id: uuid.UUID, payload: JobReassign, current_user: AdminUser, db: DbSession
) -> DataResponse[JobRead]:
    job = jobs_service.reassign_job(
        db,
        current_user.organization_id,
        job_id,
        roles=frozenset({Role.ADMIN}),
        user_id=current_user.user_id,
        employee_id=payload.employee_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))
