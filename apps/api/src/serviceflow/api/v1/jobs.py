"""Job endpoints.

Readers see every job in the tenant, technicians their own; dispatchers assign
and move work along, technicians start and finish what is assigned to them.
Those decisions are made in `services/jobs.py`, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from serviceflow.api.deps import DbSession, JobsDispatcher, JobsUser, JobsWorker
from serviceflow.auth.permissions import Permission as P
from serviceflow.core.errors import InvalidRole
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.db.models.enums import JobStatus
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.schemas.job import JobComplete, JobRead, JobReassign, JobUpdate
from serviceflow.services import bookings as bookings_service
from serviceflow.services import jobs as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=PagedResponse[JobRead], summary="List jobs")
def list_jobs(
    current_user: JobsUser,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    unassigned: Annotated[bool, Query(description="Only jobs nobody is assigned to")] = False,
    date_from: Annotated[datetime | None, Query(description="Scheduled at or after")] = None,
    date_to: Annotated[datetime | None, Query(description="Scheduled before")] = None,
    timeframe: Annotated[str | None, Query(pattern="^(upcoming|past)$")] = None,
    q: Annotated[
        str | None, Query(max_length=120, description="Customer, address or service")
    ] = None,
    sort: Annotated[str | None, Query(description="scheduled_start | created_at | status")] = None,
) -> PagedResponse[JobRead]:
    page = jobs_service.list_jobs(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        pagination=pagination,
        status=status_filter,
        employee_id=employee_id,
        unassigned=unassigned,
        date_from=date_from,
        date_to=date_to,
        timeframe=timeframe,
        q=q,
        sort=parse_sort(sort, allowed=jobs_service.JOB_SORTS, default="scheduled_start")
        if sort
        else None,
    )
    return paged(
        [JobRead.from_model(job) for job in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{job_id}", response_model=DataResponse[JobRead], summary="Get a job")
def get_job(job_id: uuid.UUID, current_user: JobsUser, db: DbSession) -> DataResponse[JobRead]:
    job = jobs_service.get_job(
        db,
        current_user.organization_id,
        job_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.patch("/{job_id}", response_model=DataResponse[JobRead], summary="Update a job")
def update_job(
    job_id: uuid.UUID, payload: JobUpdate, current_user: JobsWorker, db: DbSession
) -> DataResponse[JobRead]:
    """Move a job along its lifecycle, assign it, reschedule it, or edit its notes.

    Technicians may start and complete their own jobs and edit their notes;
    assigning, rescheduling and cancelling need JOBS_DISPATCH.
    """
    org, user_id, roles = current_user.organization_id, current_user.user_id, current_user.roles
    dispatch = current_user.can(P.JOBS_DISPATCH)

    def dispatch_only() -> None:
        if not dispatch:
            raise InvalidRole("Only dispatchers can assign, move or cancel jobs.")

    notes_applied = False
    if payload.employee_id is not None:
        dispatch_only()
        jobs_service.assign_job(
            db, org, job_id, employee_id=payload.employee_id, actor_user_id=user_id
        )
    elif payload.scheduled_start is not None:
        dispatch_only()
        job = jobs_service.get_job(db, org, job_id, roles=roles, user_id=user_id)
        bookings_service.reschedule_booking(
            db, org, job.booking_id, requested_start=payload.scheduled_start, actor_user_id=user_id
        )
    elif payload.status is JobStatus.IN_PROGRESS:
        jobs_service.start_job(db, org, job_id, roles=roles, user_id=user_id)
    elif payload.status is JobStatus.COMPLETED:
        jobs_service.complete_job(
            db, org, job_id, roles=roles, user_id=user_id, internal_notes=payload.internal_notes
        )
        notes_applied = True
    elif payload.status is JobStatus.CANCELLED:
        dispatch_only()
        jobs_service.cancel_job(db, org, job_id, user_id=user_id)

    if payload.internal_notes is not None and not notes_applied:
        jobs_service.update_notes(
            db, org, job_id, roles=roles, user_id=user_id, internal_notes=payload.internal_notes
        )

    job = jobs_service.get_job(db, org, job_id, roles=roles, user_id=user_id)
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/start", response_model=DataResponse[JobRead], summary="Start a job")
def start_job(job_id: uuid.UUID, current_user: JobsWorker, db: DbSession) -> DataResponse[JobRead]:
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
    job_id: uuid.UUID, payload: JobComplete, current_user: JobsWorker, db: DbSession
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
def cancel_job(
    job_id: uuid.UUID, current_user: JobsDispatcher, db: DbSession
) -> DataResponse[JobRead]:
    job = jobs_service.cancel_job(
        db, current_user.organization_id, job_id, user_id=current_user.user_id
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))


@router.post("/{job_id}/assign", response_model=DataResponse[JobRead], summary="Assign a job")
def assign_job(
    job_id: uuid.UUID, payload: JobReassign, current_user: JobsDispatcher, db: DbSession
) -> DataResponse[JobRead]:
    job = jobs_service.assign_job(
        db,
        current_user.organization_id,
        job_id,
        employee_id=payload.employee_id,
        actor_user_id=current_user.user_id,
    )
    return DataResponse[JobRead](data=JobRead.from_model(job))
