"""Booking endpoints.

Route handlers stay thin: resolve the caller, delegate to `services/bookings.py`,
shape the response. Scoping decisions live in the service layer so no route can
widen them.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import ActiveUser, AdminUser, DbSession
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.db.models.enums import BookingStatus, Role
from serviceflow.schemas.booking import (
    AssignableEmployee,
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingNotesUpdate,
    BookingRead,
    BookingReject,
    BookingReschedule,
)
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import bookings as bookings_service

router = APIRouter(prefix="/bookings", tags=["bookings"])

Timeframe = Annotated[
    str | None, Query(pattern="^(upcoming|past)$", description="Filter to upcoming or past")
]


@router.get("", response_model=PagedResponse[BookingRead], summary="List bookings")
def list_bookings(
    current_user: ActiveUser,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[BookingStatus | None, Query(alias="status")] = None,
    timeframe: Timeframe = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[
        str | None, Query(max_length=120, description="Customer, service or vehicle")
    ] = None,
    sort: Annotated[str | None, Query(description="requested_start | created_at | status")] = None,
) -> PagedResponse[BookingRead]:
    is_admin = current_user.has_role(Role.ADMIN)
    page = bookings_service.list_bookings(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        pagination=pagination,
        status=status_filter,
        timeframe=timeframe,
        customer_id=customer_id,
        q=q,
        sort=parse_sort(sort, allowed=bookings_service.BOOKING_SORTS, default="requested_start")
        if sort
        else None,
    )
    return paged(
        [BookingRead.from_model(booking, include_internal=is_admin) for booking in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{booking_id}", response_model=DataResponse[BookingRead], summary="Get a booking")
def get_booking(
    booking_id: uuid.UUID, current_user: ActiveUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.get_booking(
        db,
        current_user.organization_id,
        booking_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=current_user.has_role(Role.ADMIN))
    )


@router.post(
    "",
    response_model=DataResponse[BookingRead],
    status_code=status.HTTP_201_CREATED,
    summary="Request a booking",
)
def create_booking(
    payload: BookingCreate, current_user: ActiveUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.create_booking(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        customer_id=payload.customer_id,
        vehicle_id=payload.vehicle_id,
        service_id=payload.service_id,
        requested_start=payload.requested_start,
        customer_notes=payload.customer_notes,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=current_user.has_role(Role.ADMIN))
    )


@router.get(
    "/{booking_id}/assignable-employees",
    response_model=DataResponse[list[AssignableEmployee]],
    summary="Qualified employees, ranked for this booking",
)
def list_assignable_employees(
    booking_id: uuid.UUID, current_user: AdminUser, db: DbSession
) -> DataResponse[list[AssignableEmployee]]:
    """Ranked by availability, then by how light their day already is (PRD 11).

    Everyone qualified is returned, including those who are off or already busy,
    each carrying the reason - the admin should see why someone is ranked low
    rather than wonder where they went.
    """
    recommendations = bookings_service.recommended_employees(
        db, current_user.organization_id, booking_id
    )
    return DataResponse[list[AssignableEmployee]](
        data=[
            AssignableEmployee(
                id=item.employee_id,
                full_name=item.full_name,
                job_title=item.job_title,
                available=item.available,
                conflict=item.conflict,
                assignable=item.assignable,
                reason=item.reason,
                jobs_today=item.jobs_today,
                scheduled_minutes_today=item.scheduled_minutes_today,
                conflicting_job_id=item.conflicting_job_id,
            )
            for item in recommendations
        ]
    )


@router.post(
    "/{booking_id}/confirm",
    response_model=DataResponse[BookingRead],
    summary="Confirm a booking and create its job",
)
def confirm_booking(
    booking_id: uuid.UUID, payload: BookingConfirm, current_user: AdminUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.confirm_booking(
        db,
        current_user.organization_id,
        booking_id,
        employee_id=payload.employee_id,
        admin_notes=payload.admin_notes,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))


@router.post(
    "/{booking_id}/reject", response_model=DataResponse[BookingRead], summary="Reject a booking"
)
def reject_booking(
    booking_id: uuid.UUID, payload: BookingReject, current_user: AdminUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.reject_booking(
        db,
        current_user.organization_id,
        booking_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        admin_notes=payload.admin_notes,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))


@router.post(
    "/{booking_id}/cancel", response_model=DataResponse[BookingRead], summary="Cancel a booking"
)
def cancel_booking(
    booking_id: uuid.UUID, payload: BookingCancel, current_user: ActiveUser, db: DbSession
) -> DataResponse[BookingRead]:
    """Admins cancel any booking; a customer may cancel their own."""
    is_admin = current_user.has_role(Role.ADMIN)
    booking = bookings_service.cancel_booking(
        db,
        current_user.organization_id,
        booking_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        # A customer's stated reason is not written into the admin's notes.
        reason=payload.reason if is_admin else None,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=is_admin)
    )


@router.post(
    "/{booking_id}/reschedule",
    response_model=DataResponse[BookingRead],
    summary="Move a booking to a new time",
)
def reschedule_booking(
    booking_id: uuid.UUID, payload: BookingReschedule, current_user: AdminUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.reschedule_booking(
        db,
        current_user.organization_id,
        booking_id,
        requested_start=payload.requested_start,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))


@router.patch(
    "/{booking_id}", response_model=DataResponse[BookingRead], summary="Update admin notes"
)
def update_booking(
    booking_id: uuid.UUID, payload: BookingNotesUpdate, current_user: AdminUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.update_admin_notes(
        db, current_user.organization_id, booking_id, admin_notes=payload.admin_notes
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))
