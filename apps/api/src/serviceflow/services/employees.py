"""Employee business logic."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.enums import Role
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.services.people import (
    ensure_membership,
    find_or_create_user,
    set_membership_status,
)
from serviceflow.services.search import like_pattern


def list_employees(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    q: str | None = None,
    active: bool | None = None,
    service_id: uuid.UUID | None = None,
) -> Page[Employee]:
    filters = [Employee.organization_id == organization_id]
    if active is not None:
        filters.append(Employee.active.is_(active))
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
                Employee.job_title.ilike(pattern),
                (User.first_name + " " + User.last_name).ilike(pattern),
            )
        )
    if service_id is not None:
        filters.append(Employee.services.any(Service.id == service_id))

    total = db.scalar(select(func.count()).select_from(Employee).join(User).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Employee)
            .join(User)
            .where(*filters)
            .options(joinedload(Employee.user), selectinload(Employee.services))
            .order_by(Employee.active.desc(), User.first_name, User.last_name)
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def get_employee(db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
    employee = db.scalar(
        select(Employee)
        .where(Employee.id == employee_id, Employee.organization_id == organization_id)
        .options(selectinload(Employee.services))
    )
    if employee is None:
        raise NotFound("We couldn't find that employee.")
    return employee


def get_employee_for_user(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> Employee:
    employee = db.scalar(
        select(Employee)
        .where(Employee.organization_id == organization_id, Employee.user_id == user_id)
        .options(selectinload(Employee.services))
    )
    if employee is None:
        raise NotFound("You don't have an employee profile in this organization.")
    return employee


def _resolve_services(
    db: Session, organization_id: uuid.UUID, service_ids: list[uuid.UUID]
) -> list[Service]:
    """Load services, refusing any id that belongs to another organization."""
    if not service_ids:
        return []
    unique_ids = list(dict.fromkeys(service_ids))
    services = list(
        db.scalars(
            select(Service).where(
                Service.organization_id == organization_id, Service.id.in_(unique_ids)
            )
        )
    )
    if len(services) != len(unique_ids):
        raise ValidationFailed(
            "One or more of those services isn't available.",
            details={"fields": {"service_ids": "Unknown service."}},
        )
    return services


def create_employee(
    db: Session,
    organization_id: uuid.UUID,
    *,
    email: str,
    first_name: str,
    last_name: str,
    job_title: str,
    phone: str | None = None,
    service_ids: list[uuid.UUID] | None = None,
) -> Employee:
    user = find_or_create_user(
        db, email=email, first_name=first_name, last_name=last_name, phone=phone
    )

    existing = db.scalar(
        select(Employee).where(
            Employee.organization_id == organization_id, Employee.user_id == user.id
        )
    )
    if existing is not None:
        raise ValidationFailed(
            "That person is already an employee.",
            details={"fields": {"email": "Already on the team."}},
        )

    ensure_membership(db, organization_id=organization_id, user_id=user.id, role=Role.EMPLOYEE)
    employee = Employee(
        organization_id=organization_id,
        user_id=user.id,
        job_title=job_title.strip(),
    )
    employee.services = _resolve_services(db, organization_id, service_ids or [])
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def update_employee(
    db: Session,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID,
    *,
    job_title: str | None = None,
    active: bool | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    service_ids: list[uuid.UUID] | None = None,
) -> Employee:
    employee = get_employee(db, organization_id, employee_id)

    if job_title is not None:
        employee.job_title = job_title.strip()
    if first_name is not None:
        employee.user.first_name = first_name.strip()
    if last_name is not None:
        employee.user.last_name = last_name.strip()
    if phone is not None:
        employee.user.phone = phone or None
    if service_ids is not None:
        employee.services = _resolve_services(db, organization_id, service_ids)
    if active is not None and active != employee.active:
        employee.active = active
        set_membership_status(
            db,
            organization_id=organization_id,
            user_id=employee.user_id,
            role=Role.EMPLOYEE,
            active=active,
        )

    db.commit()
    db.refresh(employee)
    return employee
