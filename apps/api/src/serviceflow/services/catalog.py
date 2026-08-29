"""Service-offering business logic (the Service entity from PRD 7)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.service import Service
from serviceflow.services.search import like_pattern


def list_services(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    q: str | None = None,
    active: bool | None = None,
) -> Page[Service]:
    filters = [Service.organization_id == organization_id]
    if active is not None:
        filters.append(Service.active.is_(active))
    if q:
        pattern = like_pattern(q)
        filters.append(or_(Service.name.ilike(pattern), Service.description.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(Service).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Service)
            .where(*filters)
            .options(selectinload(Service.employees))
            .order_by(Service.active.desc(), Service.name)
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
    )
    return Page(items=items, total=total)


def get_service(db: Session, organization_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    service = db.scalar(
        select(Service)
        .where(Service.id == service_id, Service.organization_id == organization_id)
        .options(selectinload(Service.employees))
    )
    if service is None:
        raise NotFound("We couldn't find that service.")
    return service


def create_service(
    db: Session,
    organization_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
    base_price: Decimal,
    duration_minutes: int,
    image_url: str | None = None,
) -> Service:
    service = Service(
        organization_id=organization_id,
        name=name.strip(),
        description=description,
        base_price=base_price,
        duration_minutes=duration_minutes,
        image_url=image_url,
    )
    db.add(service)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationFailed(
            "A service with that name already exists.",
            details={"fields": {"name": "Already in use."}},
        ) from exc
    db.refresh(service)
    return service


def update_service(
    db: Session,
    organization_id: uuid.UUID,
    service_id: uuid.UUID,
    *,
    changes: dict[str, object],
) -> Service:
    service = get_service(db, organization_id, service_id)
    for field, value in changes.items():
        setattr(
            service, field, value.strip() if field == "name" and isinstance(value, str) else value
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValidationFailed(
            "A service with that name already exists.",
            details={"fields": {"name": "Already in use."}},
        ) from exc
    db.refresh(service)
    return service


def deactivate_service(db: Session, organization_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    """Soft delete.

    Bookings and jobs will reference services from Phase 3 onward, so removing the
    row would destroy history. Deactivating hides it from new bookings instead.
    """
    return update_service(db, organization_id, service_id, changes={"active": False})
