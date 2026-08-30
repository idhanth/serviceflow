"""Customer business logic."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnExpressionArgument, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload

from serviceflow.core.errors import Forbidden, NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import AuditAction, Role
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle
from serviceflow.services import audit
from serviceflow.services.people import ensure_membership, find_or_create_user
from serviceflow.services.search import like_pattern


def list_customers(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    q: str | None = None,
    sort: SortSpec | None = None,
) -> Page[Customer]:
    filters = [Customer.organization_id == organization_id]
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
                (User.first_name + " " + User.last_name).ilike(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(Customer).join(User).where(*filters)) or 0
    items = list(
        db.scalars(
            select(Customer)
            .join(User)
            .where(*filters)
            .options(joinedload(Customer.user))
            .order_by(*_customer_order(sort))
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).unique()
    )
    return Page(items=items, total=total)


CUSTOMER_SORTS = frozenset({"name", "created_at", "vehicles"})


def _customer_order(sort: SortSpec | None) -> list[ColumnExpressionArgument[Any]]:
    """Always ends with a unique column so paging cannot repeat or skip rows."""
    key = sort.key if sort else "name"
    descending = sort.descending if sort else False
    options: dict[str, list[InstrumentedAttribute[Any]]] = {
        "name": [User.first_name, User.last_name],
        "created_at": [Customer.created_at],
    }
    columns = options.get(key, [User.first_name, User.last_name])
    ordered = [c.desc() if descending else c.asc() for c in columns]
    return [*ordered, Customer.id.asc()]


def get_customer(db: Session, organization_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id, Customer.organization_id == organization_id
        )
    )
    if customer is None:
        raise NotFound("We couldn't find that customer.")
    return customer


def get_customer_for_user(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.organization_id == organization_id, Customer.user_id == user_id
        )
    )
    if customer is None:
        raise NotFound("You don't have a customer profile in this organization.")
    return customer


def resolve_accessible_customer(
    db: Session,
    organization_id: uuid.UUID,
    *,
    roles: frozenset[Role],
    user_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> Customer:
    """Decide which customer record a caller may act on.

    Admins may name any customer in their organization. A customer may only ever
    reach their own record, whether they name it explicitly or not - naming
    someone else's is refused rather than silently redirected.
    """
    if Role.ADMIN in roles:
        if customer_id is None:
            raise ValidationFailed(
                "Choose a customer.", details={"fields": {"customer_id": "Required."}}
            )
        return get_customer(db, organization_id, customer_id)

    own = get_customer_for_user(db, organization_id, user_id)
    if customer_id is not None and customer_id != own.id:
        raise Forbidden("You can only manage your own records.")
    return own


def count_vehicles(
    db: Session, organization_id: uuid.UUID, customer_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Vehicle counts for a page of customers, in one query rather than N."""
    if not customer_ids:
        return {}
    rows = db.execute(
        select(Vehicle.customer_id, func.count())
        .where(Vehicle.organization_id == organization_id, Vehicle.customer_id.in_(customer_ids))
        .group_by(Vehicle.customer_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def create_customer(
    db: Session,
    organization_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    email: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    notes: str | None = None,
) -> Customer:
    user = find_or_create_user(
        db, email=email, first_name=first_name, last_name=last_name, phone=phone
    )

    existing = db.scalar(
        select(Customer).where(
            Customer.organization_id == organization_id, Customer.user_id == user.id
        )
    )
    if existing is not None:
        raise ValidationFailed(
            "That person is already a customer.",
            details={"fields": {"email": "Already a customer of this organization."}},
        )

    ensure_membership(db, organization_id=organization_id, user_id=user.id, role=Role.CUSTOMER)
    customer = Customer(organization_id=organization_id, user_id=user.id, notes=notes)
    db.add(customer)
    db.flush()
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.CUSTOMER_CREATED,
        resource_type="customer",
        resource_id=customer.id,
        # The person's name, not their contact details: enough to know who was
        # added without copying personal data into a table nobody can edit.
        metadata={"customer": user.full_name},
    )
    db.commit()
    db.refresh(customer)
    return customer


def update_customer(
    db: Session,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    notes: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    update_notes: bool = False,
) -> Customer:
    customer = get_customer(db, organization_id, customer_id)
    if update_notes:
        customer.notes = notes
    if first_name is not None:
        customer.user.first_name = first_name.strip()
    if last_name is not None:
        customer.user.last_name = last_name.strip()
    if phone is not None:
        customer.user.phone = phone or None
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.CUSTOMER_UPDATED,
        resource_type="customer",
        resource_id=customer.id,
        # Which fields changed, never the values - a phone number does not
        # belong in an append-only table.
        metadata={
            "customer": customer.user.full_name,
            "fields": ", ".join(
                name
                for name, changed in (
                    ("notes", update_notes),
                    ("first_name", first_name is not None),
                    ("last_name", last_name is not None),
                    ("phone", phone is not None),
                )
                if changed
            )
            or "none",
        },
    )
    db.commit()
    db.refresh(customer)
    return customer
