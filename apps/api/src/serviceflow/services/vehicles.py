"""Vehicle business logic.

Every read and write funnels through a customer scope: an admin may act across
their organization, a customer only on their own vehicles (PRD 6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from serviceflow.core.errors import Forbidden, NotFound
from serviceflow.core.pagination import Page, PageParams
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import Role
from serviceflow.db.models.vehicle import Vehicle
from serviceflow.services.customers import get_customer, get_customer_for_user
from serviceflow.services.search import like_pattern


def _customer_filter(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Return the customer id a listing must be pinned to, or None for org-wide.

    A non-admin is always pinned to their own record, so no query path exists
    that could return another customer's vehicles.
    """
    if Role.ADMIN in roles:
        if customer_id is not None:
            get_customer(db, organization_id, customer_id)  # 404s on a foreign id
        return customer_id
    own = get_customer_for_user(db, organization_id, user_id)
    if customer_id is not None and customer_id != own.id:
        raise Forbidden("You can only view your own vehicles.")
    return own.id


def list_vehicles(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    pagination: PageParams,
    q: str | None = None,
    customer_id: uuid.UUID | None = None,
) -> Page[Vehicle]:
    scope = _customer_filter(
        db, organization_id, roles=roles, user_id=user_id, customer_id=customer_id
    )

    filters = [Vehicle.organization_id == organization_id, Vehicle.archived_at.is_(None)]
    if scope is not None:
        filters.append(Vehicle.customer_id == scope)
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
                Vehicle.color.ilike(pattern),
                Vehicle.license_plate.ilike(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(Vehicle).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Vehicle)
            .where(*filters)
            .options(joinedload(Vehicle.customer).joinedload(Customer.user))
            .order_by(Vehicle.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


def get_vehicle(
    db: Session,
    organization_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    include_archived: bool = False,
) -> Vehicle:
    """Load a vehicle the caller may see.

    `include_archived` is for records that reference a vehicle historically - a
    booking or job still has to render the car it was for.
    """
    filters = [Vehicle.id == vehicle_id, Vehicle.organization_id == organization_id]
    if not include_archived:
        filters.append(Vehicle.archived_at.is_(None))

    vehicle = db.scalar(
        select(Vehicle)
        .where(*filters)
        .options(joinedload(Vehicle.customer).joinedload(Customer.user))
    )
    if vehicle is None:
        raise NotFound("We couldn't find that vehicle.")

    if Role.ADMIN not in roles:
        own = get_customer_for_user(db, organization_id, user_id)
        # Not-yours reads the same as not-found, so ids cannot be probed.
        if vehicle.customer_id != own.id:
            raise NotFound("We couldn't find that vehicle.")
    return vehicle


def create_vehicle(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    year: int,
    make: str,
    model: str,
    color: str | None = None,
    license_plate: str | None = None,
    notes: str | None = None,
) -> Vehicle:
    if Role.ADMIN in roles:
        if customer_id is None:
            raise NotFound("Choose a customer for this vehicle.")
        owner = get_customer(db, organization_id, customer_id)
    else:
        owner = get_customer_for_user(db, organization_id, user_id)
        if customer_id is not None and customer_id != owner.id:
            raise Forbidden("You can only add vehicles to your own account.")

    vehicle = Vehicle(
        organization_id=organization_id,
        customer_id=owner.id,
        year=year,
        make=make.strip(),
        model=model.strip(),
        color=(color or "").strip() or None,
        license_plate=(license_plate or "").strip().upper() or None,
        notes=notes,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def update_vehicle(
    db: Session,
    organization_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    changes: dict[str, object],
) -> Vehicle:
    vehicle = get_vehicle(db, organization_id, vehicle_id, roles=roles, user_id=user_id)
    for field, value in changes.items():
        if field == "license_plate" and isinstance(value, str):
            value = value.strip().upper() or None
        elif isinstance(value, str) and field in {"make", "model", "color"}:
            value = value.strip() or None
        setattr(vehicle, field, value)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def archive_vehicle(
    db: Session,
    organization_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
) -> Vehicle:
    """Archive rather than delete, so bookings and jobs keep their vehicle.

    Archiving is idempotent: archiving an already-archived vehicle is a no-op
    rather than an error, so a double-submitted request stays safe.
    """
    vehicle = get_vehicle(
        db, organization_id, vehicle_id, roles=roles, user_id=user_id, include_archived=True
    )
    if vehicle.archived_at is None:
        vehicle.archived_at = datetime.now(UTC)
        db.commit()
        db.refresh(vehicle)
    return vehicle
