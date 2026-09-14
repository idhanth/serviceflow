"""Customer business logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnExpressionArgument, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload

from serviceflow.core.errors import NotFound, ValidationFailed
from serviceflow.core.pagination import Page, PageParams, SortSpec
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.enums import AuditAction, JobStatus, Role
from serviceflow.db.models.job import Job
from serviceflow.db.models.user import User
from serviceflow.services import audit
from serviceflow.services.people import ensure_membership, find_or_create_user
from serviceflow.services.search import like_pattern


def list_customers(
    db: Session,
    organization_id: uuid.UUID,
    *,
    pagination: PageParams,
    q: str | None = None,
    include_archived: bool = False,
    sort: SortSpec | None = None,
) -> Page[Customer]:
    filters: list[ColumnExpressionArgument[bool]] = [Customer.organization_id == organization_id]
    if not include_archived:
        filters.append(Customer.archived_at.is_(None))
    if q:
        pattern = like_pattern(q)
        filters.append(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
                Customer.address.ilike(pattern),
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


CUSTOMER_SORTS = frozenset({"name", "created_at"})


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
    """A customer of *this* organization. Another tenant's id reads as not found."""
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


def history_counts(
    db: Session, organization_id: uuid.UUID, customer_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Booking count, completed jobs and last visit for a page of customers.

    Two grouped queries for the whole page rather than several per row.
    """
    if not customer_ids:
        return {}
    summary: dict[uuid.UUID, dict[str, Any]] = {
        customer_id: {"booking_count": 0, "completed_jobs": 0, "last_service_at": None}
        for customer_id in customer_ids
    }
    for customer_id, count in db.execute(
        select(Booking.customer_id, func.count())
        .where(Booking.organization_id == organization_id, Booking.customer_id.in_(customer_ids))
        .group_by(Booking.customer_id)
    ).all():
        summary[customer_id]["booking_count"] = int(count)
    for customer_id, completed, last in db.execute(
        select(Booking.customer_id, func.count(), func.max(Job.completed_at))
        .join(Job, Job.booking_id == Booking.id)
        .where(
            Booking.organization_id == organization_id,
            Booking.customer_id.in_(customer_ids),
            Job.status == JobStatus.COMPLETED,
        )
        .group_by(Booking.customer_id)
    ).all():
        summary[customer_id]["completed_jobs"] = int(completed)
        summary[customer_id]["last_service_at"] = last
    return summary


def create_customer(
    db: Session,
    organization_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    email: str,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    address: str | None = None,
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
    customer = Customer(
        organization_id=organization_id,
        user_id=user.id,
        address=(address or "").strip() or None,
        notes=notes,
    )
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
    changes: dict[str, Any],
) -> Customer:
    customer = get_customer(db, organization_id, customer_id)
    if "notes" in changes:
        customer.notes = changes["notes"]
    if "address" in changes:
        customer.address = (changes["address"] or "").strip() or None
    if changes.get("first_name") is not None:
        customer.user.first_name = changes["first_name"].strip()
    if changes.get("last_name") is not None:
        customer.user.last_name = changes["last_name"].strip()
    if "phone" in changes:
        customer.user.phone = changes["phone"] or None
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
            "fields": ", ".join(sorted(changes)) or "none",
        },
    )
    db.commit()
    db.refresh(customer)
    return customer


def archive_customer(
    db: Session, organization_id: uuid.UUID, customer_id: uuid.UUID, *, actor_user_id: uuid.UUID
) -> Customer:
    """Hide a customer from lists and new bookings while keeping their history.

    Refused while they still have open bookings, so an archived customer never
    has a technician on the way.
    """
    customer = get_customer(db, organization_id, customer_id)
    if customer.archived:
        return customer
    open_bookings = db.scalar(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.organization_id == organization_id,
            Booking.customer_id == customer.id,
            Booking.status.in_(["PENDING", "CONFIRMED"]),
            Booking.requested_start >= datetime.now(UTC),
        )
    )
    if open_bookings:
        raise ValidationFailed(
            f"{customer.user.full_name} has {open_bookings} upcoming booking"
            f"{'s' if open_bookings != 1 else ''}. Cancel them before archiving.",
            details={"fields": {"customer_id": "Has upcoming bookings."}},
        )
    customer.archived_at = datetime.now(UTC)
    audit.record(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=AuditAction.CUSTOMER_ARCHIVED,
        resource_type="customer",
        resource_id=customer.id,
        metadata={"customer": customer.user.full_name},
    )
    db.commit()
    db.refresh(customer)
    return customer
