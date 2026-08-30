"""Employee availability endpoints.

One set of routes serves both audiences: admins may address any employee in the
organization, an employee only themselves. `resolve_manageable_employee` makes
that call in the service layer, so no route can widen it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from serviceflow.api.deps import DbSession, EmployeeUser
from serviceflow.schemas.availability import (
    AvailabilityRead,
    OverrideInput,
    OverrideRead,
    WeeklyScheduleUpdate,
)
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services import schedules as schedules_service
from serviceflow.services.scheduling import organization_timezone

router = APIRouter(prefix="/employees/{employee_id}/availability", tags=["availability"])


def _read(db: DbSession, employee, since: dt.date | None) -> AvailabilityRead:  # type: ignore[no-untyped-def]
    return AvailabilityRead.build(
        employee_id=employee.id,
        full_name=employee.user.full_name,
        timezone=organization_timezone(db, employee.organization_id),
        weekly=schedules_service.get_weekly(db, employee),
        overrides=schedules_service.get_overrides(db, employee, since=since),
    )


@router.get(
    "", response_model=DataResponse[AvailabilityRead], summary="Weekly schedule and overrides"
)
def get_availability(
    employee_id: uuid.UUID,
    current_user: EmployeeUser,
    db: DbSession,
    include_past: Annotated[bool, Query(description="Include overrides before today")] = False,
) -> DataResponse[AvailabilityRead]:
    employee = schedules_service.resolve_manageable_employee(
        db,
        current_user.organization_id,
        employee_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    since = None if include_past else dt.date.today()
    return DataResponse[AvailabilityRead](data=_read(db, employee, since))


@router.put(
    "", response_model=DataResponse[AvailabilityRead], summary="Replace the weekly schedule"
)
def replace_weekly(
    employee_id: uuid.UUID,
    payload: WeeklyScheduleUpdate,
    current_user: EmployeeUser,
    db: DbSession,
) -> DataResponse[AvailabilityRead]:
    employee = schedules_service.resolve_manageable_employee(
        db,
        current_user.organization_id,
        employee_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    schedules_service.replace_weekly(
        db,
        employee,
        [(w.day_of_week, w.start_time, w.end_time) for w in payload.windows],
    )
    return DataResponse[AvailabilityRead](data=_read(db, employee, dt.date.today()))


@router.post(
    "/overrides",
    response_model=DataResponse[OverrideRead],
    status_code=status.HTTP_201_CREATED,
    summary="Set the override for one date",
)
def upsert_override(
    employee_id: uuid.UUID,
    payload: OverrideInput,
    current_user: EmployeeUser,
    db: DbSession,
) -> DataResponse[OverrideRead]:
    """Upsert: one override per date keeps the precedence rules unambiguous."""
    employee = schedules_service.resolve_manageable_employee(
        db,
        current_user.organization_id,
        employee_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    override = schedules_service.upsert_override(
        db,
        employee,
        date=payload.date,
        available=payload.available,
        start_time=payload.start_time,
        end_time=payload.end_time,
        reason=payload.reason,
    )
    return DataResponse[OverrideRead](data=OverrideRead.model_validate(override))


@router.delete(
    "/overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a date override",
)
def delete_override(
    employee_id: uuid.UUID,
    override_id: uuid.UUID,
    current_user: EmployeeUser,
    db: DbSession,
) -> Response:
    employee = schedules_service.resolve_manageable_employee(
        db,
        current_user.organization_id,
        employee_id,
        roles=current_user.roles,
        user_id=current_user.user_id,
    )
    schedules_service.delete_override(db, employee, override_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
