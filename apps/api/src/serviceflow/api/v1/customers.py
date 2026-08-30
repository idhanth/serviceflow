"""Customer endpoints.

Listing and managing customers is admin-only. A customer reaches exactly one
record - their own - through /customers/me.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import ActiveUser, AdminUser, DbSession
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import customers as customers_service

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=PagedResponse[CustomerRead], summary="List customers")
def list_customers(
    current_user: AdminUser,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[str | None, Query(max_length=120, description="Name, email or phone")] = None,
    sort: Annotated[str | None, Query(description="name | created_at, prefix - to reverse")] = None,
) -> PagedResponse[CustomerRead]:
    page = customers_service.list_customers(
        db,
        current_user.organization_id,
        pagination=pagination,
        q=q,
        sort=parse_sort(sort, allowed=customers_service.CUSTOMER_SORTS, default="name"),
    )
    counts = customers_service.count_vehicles(
        db, current_user.organization_id, [customer.id for customer in page.items]
    )
    return paged(
        [
            CustomerRead.from_model(customer, vehicle_count=counts.get(customer.id, 0))
            for customer in page.items
        ],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/me", response_model=DataResponse[CustomerRead], summary="Own customer profile")
def get_own_customer(current_user: ActiveUser, db: DbSession) -> DataResponse[CustomerRead]:
    customer = customers_service.get_customer_for_user(
        db, current_user.organization_id, current_user.user_id
    )
    counts = customers_service.count_vehicles(db, current_user.organization_id, [customer.id])
    return DataResponse[CustomerRead](
        data=CustomerRead.from_model(customer, vehicle_count=counts.get(customer.id, 0))
    )


@router.get("/{customer_id}", response_model=DataResponse[CustomerRead], summary="Get a customer")
def get_customer(
    customer_id: uuid.UUID, current_user: AdminUser, db: DbSession
) -> DataResponse[CustomerRead]:
    customer = customers_service.get_customer(db, current_user.organization_id, customer_id)
    counts = customers_service.count_vehicles(db, current_user.organization_id, [customer.id])
    return DataResponse[CustomerRead](
        data=CustomerRead.from_model(customer, vehicle_count=counts.get(customer.id, 0))
    )


@router.post(
    "",
    response_model=DataResponse[CustomerRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a customer",
)
def create_customer(
    payload: CustomerCreate, current_user: AdminUser, db: DbSession
) -> DataResponse[CustomerRead]:
    customer = customers_service.create_customer(
        db,
        current_user.organization_id,
        actor_user_id=current_user.user_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        notes=payload.notes,
    )
    return DataResponse[CustomerRead](data=CustomerRead.from_model(customer))


@router.patch(
    "/{customer_id}", response_model=DataResponse[CustomerRead], summary="Update a customer"
)
def update_customer(
    customer_id: uuid.UUID, payload: CustomerUpdate, current_user: AdminUser, db: DbSession
) -> DataResponse[CustomerRead]:
    changes = payload.model_dump(exclude_unset=True)
    customer = customers_service.update_customer(
        db,
        current_user.organization_id,
        customer_id,
        actor_user_id=current_user.user_id,
        notes=changes.get("notes"),
        update_notes="notes" in changes,
        first_name=changes.get("first_name"),
        last_name=changes.get("last_name"),
        phone=changes.get("phone"),
    )
    counts = customers_service.count_vehicles(db, current_user.organization_id, [customer.id])
    return DataResponse[CustomerRead](
        data=CustomerRead.from_model(customer, vehicle_count=counts.get(customer.id, 0))
    )
