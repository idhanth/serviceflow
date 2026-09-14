"""Booking endpoints.

Route handlers stay thin: resolve the caller, delegate to `services/bookings.py`,
shape the response. Scoping decisions live in the service layer so no route can
widen them; the permission guards here only decide who may knock on the door.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from serviceflow.api.deps import (
    BookingsCreator,
    BookingsUser,
    BookingsWriter,
    DbSession,
    rate_limit_user,
)
from serviceflow.auth.permissions import Permission as P
from serviceflow.core.errors import InvalidRole, NotFound
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.db.models.enums import BookingStatus
from serviceflow.schemas.booking import (
    AssignableEmployee,
    BookingCancel,
    BookingConfirm,
    BookingCreate,
    BookingRead,
    BookingReject,
    BookingReschedule,
    BookingUpdate,
)
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import bookings as bookings_service
from serviceflow.services import idempotency
from serviceflow.services import jobs as jobs_service

router = APIRouter(prefix="/bookings", tags=["bookings"])

Timeframe = Annotated[
    str | None, Query(pattern="^(upcoming|past)$", description="Filter to upcoming or past")
]


@router.get("", response_model=PagedResponse[BookingRead], summary="List bookings")
def list_bookings(
    current_user: BookingsUser,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[BookingStatus | None, Query(alias="status")] = None,
    timeframe: Timeframe = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(description="Starts at or after")] = None,
    date_to: Annotated[datetime | None, Query(description="Starts before")] = None,
    q: Annotated[str | None, Query(max_length=120, description="Customer or service")] = None,
    sort: Annotated[str | None, Query(description="requested_start | created_at | status")] = None,
) -> PagedResponse[BookingRead]:
    internal = current_user.can(P.BOOKINGS_READ)
    page = bookings_service.list_bookings(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        pagination=pagination,
        status=status_filter,
        timeframe=timeframe,
        customer_id=customer_id,
        employee_id=employee_id,
        service_id=service_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        sort=parse_sort(sort, allowed=bookings_service.BOOKING_SORTS, default="requested_start")
        if sort
        else None,
    )
    return paged(
        [BookingRead.from_model(booking, include_internal=internal) for booking in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/{booking_id}", response_model=DataResponse[BookingRead], summary="Get a booking")
def get_booking(
    booking_id: uuid.UUID, current_user: BookingsUser, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.get_booking(
        db,
        current_user.organization_id,
        booking_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=current_user.can(P.BOOKINGS_READ))
    )


@router.post(
    "",
    response_model=DataResponse[BookingRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a booking",
    dependencies=[Depends(rate_limit_user("booking_create"))],
)
def create_booking(
    payload: BookingCreate,
    current_user: BookingsCreator,
    db: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataResponse[BookingRead]:
    """Create a booking and its job, optionally idempotently.

    With an `Idempotency-Key`, a retry of the same request returns the original
    booking instead of making a second one, and the same key with a different
    body is refused as a conflict. The key is scoped to this organization and
    this user, so the same string from someone else never collides.
    """
    internal = current_user.can(P.BOOKINGS_READ)
    hook = None

    if idempotency_key is not None:
        fields = payload.model_dump(mode="json")
        replay = idempotency.begin(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
            key=idempotency_key,
            operation="create_booking",
            payload=fields,
        )
        if replay is not None:
            # The original result, not a new booking.
            booking = bookings_service.get_booking(
                db,
                current_user.organization_id,
                replay.resource_id,
                roles=current_user.roles,
                user_id=current_user.user_id,
            )
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotent-Replay"] = "true"
            return DataResponse[BookingRead](
                data=BookingRead.from_model(booking, include_internal=internal)
            )

        def hook(session, created):  # type: ignore[no-untyped-def]
            # Staged inside the booking's transaction: a rollback takes the
            # record with it, so no record can claim a booking that never existed.
            idempotency.complete(
                session,
                organization_id=current_user.organization_id,
                user_id=current_user.user_id,
                key=idempotency_key,
                resource_type="booking",
                resource_id=created.id,
                response_status=status.HTTP_201_CREATED,
                response_body={"booking_id": str(created.id)},
            )

    booking = bookings_service.create_booking(
        db,
        current_user.organization_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        customer_id=payload.customer_id,
        service_id=payload.service_id,
        employee_id=payload.employee_id,
        requested_start=payload.requested_start,
        customer_notes=payload.customer_notes,
        before_commit=hook,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=internal)
    )


@router.patch("/{booking_id}", response_model=DataResponse[BookingRead], summary="Update a booking")
def update_booking(
    booking_id: uuid.UUID, payload: BookingUpdate, current_user: BookingsCreator, db: DbSession
) -> DataResponse[BookingRead]:
    """One change per request: cancel, reject, assign a technician, move, or edit notes.

    Customers may only cancel their own bookings. Everything else needs
    BOOKINGS_WRITE, and each change runs through the same service function as
    its dedicated action endpoint.
    """
    org, user_id, roles = current_user.organization_id, current_user.user_id, current_user.roles
    staff = current_user.can(P.BOOKINGS_WRITE)

    if payload.status is BookingStatus.CANCELLED:
        booking = bookings_service.cancel_booking(
            db, org, booking_id, roles=roles, user_id=user_id, reason=payload.reason
        )
    elif not staff:
        raise InvalidRole("You can cancel a booking; other changes go through the business.")
    elif payload.employee_id is not None:
        current = bookings_service.load_booking(db, org, booking_id)
        if current.status is BookingStatus.PENDING:
            booking = bookings_service.confirm_booking(
                db,
                org,
                booking_id,
                employee_id=payload.employee_id,
                admin_notes=payload.admin_notes,
                actor_user_id=user_id,
            )
        else:
            if current.job is None:  # pragma: no cover - created together
                raise NotFound("We couldn't find the job for that booking.")
            jobs_service.assign_job(
                db, org, current.job.id, employee_id=payload.employee_id, actor_user_id=user_id
            )
            booking = bookings_service.load_booking(db, org, booking_id)
    elif payload.status is BookingStatus.REJECTED:
        booking = bookings_service.reject_booking(
            db, org, booking_id, user_id=user_id, admin_notes=payload.admin_notes
        )
    elif payload.requested_start is not None:
        booking = bookings_service.reschedule_booking(
            db, org, booking_id, requested_start=payload.requested_start, actor_user_id=user_id
        )
    else:
        booking = bookings_service.load_booking(db, org, booking_id)

    if staff and payload.admin_notes is not None and payload.status is not BookingStatus.REJECTED:
        booking = bookings_service.update_admin_notes(
            db, org, booking_id, admin_notes=payload.admin_notes
        )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=current_user.can(P.BOOKINGS_READ))
    )


@router.get(
    "/{booking_id}/assignable-employees",
    response_model=DataResponse[list[AssignableEmployee]],
    summary="Qualified employees, ranked for this booking",
)
def list_assignable_employees(
    booking_id: uuid.UUID, current_user: BookingsWriter, db: DbSession
) -> DataResponse[list[AssignableEmployee]]:
    """Ranked by availability, then by how light their day already is.

    Everyone qualified is returned, including those who are off or already busy,
    each carrying the reason - the dispatcher should see why someone is ranked
    low rather than wonder where they went.
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
    summary="Assign a technician, confirming the booking",
)
def confirm_booking(
    booking_id: uuid.UUID, payload: BookingConfirm, current_user: BookingsWriter, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.confirm_booking(
        db,
        current_user.organization_id,
        booking_id,
        employee_id=payload.employee_id,
        admin_notes=payload.admin_notes,
        actor_user_id=current_user.user_id,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))


@router.post(
    "/{booking_id}/reject", response_model=DataResponse[BookingRead], summary="Reject a booking"
)
def reject_booking(
    booking_id: uuid.UUID, payload: BookingReject, current_user: BookingsWriter, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.reject_booking(
        db,
        current_user.organization_id,
        booking_id,
        user_id=current_user.user_id,
        admin_notes=payload.admin_notes,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))


@router.post(
    "/{booking_id}/cancel", response_model=DataResponse[BookingRead], summary="Cancel a booking"
)
def cancel_booking(
    booking_id: uuid.UUID, payload: BookingCancel, current_user: BookingsCreator, db: DbSession
) -> DataResponse[BookingRead]:
    """Staff cancel any booking; a customer may cancel their own."""
    booking = bookings_service.cancel_booking(
        db,
        current_user.organization_id,
        booking_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
        reason=payload.reason,
    )
    return DataResponse[BookingRead](
        data=BookingRead.from_model(booking, include_internal=current_user.can(P.BOOKINGS_READ))
    )


@router.post(
    "/{booking_id}/reschedule",
    response_model=DataResponse[BookingRead],
    summary="Move a booking to a new time",
)
def reschedule_booking(
    booking_id: uuid.UUID, payload: BookingReschedule, current_user: BookingsWriter, db: DbSession
) -> DataResponse[BookingRead]:
    booking = bookings_service.reschedule_booking(
        db,
        current_user.organization_id,
        booking_id,
        requested_start=payload.requested_start,
        actor_user_id=current_user.user_id,
    )
    return DataResponse[BookingRead](data=BookingRead.from_model(booking, include_internal=True))
