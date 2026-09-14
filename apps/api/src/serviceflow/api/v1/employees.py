"""Employee endpoints.

Owners, managers, dispatchers and analysts read the roster; owners and managers
change it. Technicians read their own profile via /employees/me.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import ActiveUser, DbSession, EmployeesReader, EmployeesWriter
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.schemas.employee import EmployeeCreate, EmployeeRead, EmployeeUpdate
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import employees as employees_service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=PagedResponse[EmployeeRead], summary="List employees")
def list_employees(
    current_user: EmployeesReader,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[str | None, Query(max_length=120, description="Name, email or job title")] = None,
    active: Annotated[bool | None, Query()] = None,
    service_id: Annotated[uuid.UUID | None, Query(description="Only those who perform it")] = None,
    sort: Annotated[str | None, Query(description="name | job_title | created_at")] = None,
) -> PagedResponse[EmployeeRead]:
    page = employees_service.list_employees(
        db,
        current_user.organization_id,
        pagination=pagination,
        q=q,
        active=active,
        service_id=service_id,
        sort=parse_sort(sort, allowed=employees_service.EMPLOYEE_SORTS, default="name"),
    )
    return paged(
        [EmployeeRead.from_model(employee) for employee in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/me", response_model=DataResponse[EmployeeRead], summary="Own employee profile")
def get_own_employee(current_user: ActiveUser, db: DbSession) -> DataResponse[EmployeeRead]:
    employee = employees_service.get_employee_for_user(
        db, current_user.organization_id, current_user.user_id
    )
    return DataResponse[EmployeeRead](data=EmployeeRead.from_model(employee))


@router.get("/{employee_id}", response_model=DataResponse[EmployeeRead], summary="Get an employee")
def get_employee(
    employee_id: uuid.UUID, current_user: EmployeesReader, db: DbSession
) -> DataResponse[EmployeeRead]:
    employee = employees_service.get_employee(db, current_user.organization_id, employee_id)
    return DataResponse[EmployeeRead](data=EmployeeRead.from_model(employee))


@router.post(
    "",
    response_model=DataResponse[EmployeeRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add an employee",
)
def create_employee(
    payload: EmployeeCreate, current_user: EmployeesWriter, db: DbSession
) -> DataResponse[EmployeeRead]:
    employee = employees_service.create_employee(
        db,
        current_user.organization_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        job_title=payload.job_title,
        phone=payload.phone,
        service_ids=payload.service_ids,
        actor_user_id=current_user.user_id,
    )
    return DataResponse[EmployeeRead](data=EmployeeRead.from_model(employee))


@router.patch(
    "/{employee_id}", response_model=DataResponse[EmployeeRead], summary="Update an employee"
)
def update_employee(
    employee_id: uuid.UUID, payload: EmployeeUpdate, current_user: EmployeesWriter, db: DbSession
) -> DataResponse[EmployeeRead]:
    changes = payload.model_dump(exclude_unset=True)
    employee = employees_service.update_employee(
        db,
        current_user.organization_id,
        employee_id,
        job_title=changes.get("job_title"),
        active=changes.get("active"),
        first_name=changes.get("first_name"),
        last_name=changes.get("last_name"),
        phone=changes.get("phone"),
        service_ids=changes.get("service_ids"),
        actor_user_id=current_user.user_id,
    )
    return DataResponse[EmployeeRead](data=EmployeeRead.from_model(employee))
