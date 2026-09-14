"""Who could do a piece of work at a proposed time, before any booking exists.

The booking form asks this as someone picks a service and a slot, so the
technician step can show who is free - and why the others are not - instead of
letting the person submit and find out from a conflict.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from sqlalchemy import select

from serviceflow.api.deps import BookingsCreator, DbSession
from serviceflow.auth.permissions import Permission as P
from serviceflow.core.errors import NotFound
from serviceflow.db.models.service import Service
from serviceflow.schemas.booking import AssignableEmployee
from serviceflow.schemas.envelope import DataResponse
from serviceflow.services.bookings import booking_window
from serviceflow.services.recommendations import recommend_employees

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


@router.get(
    "/candidates",
    response_model=DataResponse[list[AssignableEmployee]],
    summary="Qualified technicians for a service at a proposed time, ranked",
)
def candidates(
    current_user: BookingsCreator,
    db: DbSession,
    service_id: Annotated[uuid.UUID, Query()],
    start: Annotated[AwareDatetime, Query()],
) -> DataResponse[list[AssignableEmployee]]:
    service = db.scalar(
        select(Service).where(
            Service.id == service_id,
            Service.organization_id == current_user.organization_id,
            Service.active.is_(True),
        )
    )
    if service is None:
        raise NotFound("We couldn't find that service.")
    window_start, window_end = booking_window(service, start)
    ranked = recommend_employees(
        db,
        current_user.organization_id,
        service=service,
        start=window_start,
        end=window_end,
    )
    # A customer choosing a technician needs who is free, not a colleague's workload.
    staff = current_user.can(P.BOOKINGS_WRITE)
    return DataResponse[list[AssignableEmployee]](
        data=[
            AssignableEmployee(
                id=item.employee_id,
                full_name=item.full_name,
                job_title=item.job_title,
                available=item.available,
                conflict=item.conflict,
                assignable=item.assignable,
                reason=item.reason if staff or not item.assignable else None,
                jobs_today=item.jobs_today if staff else 0,
                scheduled_minutes_today=item.scheduled_minutes_today if staff else 0,
                conflicting_job_id=item.conflicting_job_id if staff else None,
            )
            for item in ranked
            if staff or item.assignable
        ]
    )
