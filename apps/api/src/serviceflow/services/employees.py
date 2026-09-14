"""Employee business logic."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnExpressionArgument, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload, selectinload

from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.employee import Employee, EmployeeService
from serviceflow.db.models.enums import AuditAction, Role
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.services import audit
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
    sort: SortSpec | None = None,
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
            .order_by(*_employee_order(sort))
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


EMPLOYEE_SORTS = frozenset({"name", "job_title", "created_at"})


def _employee_order(sort: SortSpec | None) -> list[ColumnExpressionArgument[Any]]:
    key = sort.key if sort else "name"
    descending = sort.descending if sort else False
    options: dict[str, list[InstrumentedAttribute[Any]]] = {
        "name": [User.first_name, User.last_name],
        "job_title": [Employee.job_title],
        "created_at": [Employee.created_at],
    }
    columns = options.get(key, [User.first_name, User.last_name])
    ordered = [c.desc() if descending else c.asc() for c in columns]
    # Active first regardless, then the chosen sort, then a unique tiebreak.
    return [Employee.active.desc(), *ordered, Employee.id.asc()]


def get_employee(db: Session, organization_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
    employee = db.scalar(
        select(Employee)
        .where(Employee.id == employee_id, Employee.organization_id == organization_id)
        .options(selectinload(Employee.services), selectinload(Employee.service_links))
        .execution_options(populate_existing=True)
    )
    if employee is None:
        raise NotFound("We couldn't find that employee.")
    return employee


def find_employee_for_user(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID
) -> Employee | None:
    return db.scalar(
        select(Employee)
        .where(Employee.organization_id == organization_id, Employee.user_id == user_id)
        .options(selectinload(Employee.services))
    )


def get_employee_for_user(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> Employee:
    employee = find_employee_for_user(db, organization_id, user_id)
    if employee is None:
        raise NotFound("You don't have an employee profile in this organization.")
    return employee


def set_qualifications(employee: Employee, services: list[Service]) -> None:
    """Replace an employee's qualifications.

    Written through the link rows, which carry the tenant id so the composite
    foreign keys can hold the employee and service to one organization.
    """
    wanted = {service.id for service in services}
    employee.service_links = [
        link for link in employee.service_links if link.service_id in wanted
    ] + [
        EmployeeService(
            organization_id=employee.organization_id,
            employee_id=employee.id,
            service_id=service_id,
        )
        for service_id in sorted(wanted - {link.service_id for link in employee.service_links})
    ]


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
    actor_user_id: uuid.UUID | None = None,
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

    ensure_membership(db, organization_id=organization_id, user_id=user.id, role=Role.TECHNICIAN)
    employee = Employee(
        id=uuid.uuid4(),
        organization_id=organization_id,
        user_id=user.id,
        job_title=job_title.strip(),
    )
    db.add(employee)
    db.flush()
    set_qualifications(employee, _resolve_services(db, organization_id, service_ids or []))
    db.flush()
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.EMPLOYEE_CREATED,
        resource_type="employee",
        resource_id=employee.id,
        metadata={"name": user.full_name, "job_title": employee.job_title},
    )
    db.commit()
    return get_employee(db, organization_id, employee.id)


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
    actor_user_id: uuid.UUID | None = None,
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
        set_qualifications(employee, _resolve_services(db, organization_id, service_ids))
    activation_changed = active is not None and active != employee.active
    if activation_changed:
        employee.active = bool(active)
        set_membership_status(
            db,
            organization_id=organization_id,
            user_id=employee.user_id,
            role=Role.TECHNICIAN,
            active=bool(active),
        )

    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=(
            (AuditAction.EMPLOYEE_REACTIVATED if active else AuditAction.EMPLOYEE_DEACTIVATED)
            if activation_changed
            else AuditAction.EMPLOYEE_UPDATED
        ),
        resource_type="employee",
        resource_id=employee.id,
        metadata={"name": employee.user.full_name, "job_title": employee.job_title},
    )
    db.commit()
    db.expire_all()
    return get_employee(db, organization_id, employee_id)
