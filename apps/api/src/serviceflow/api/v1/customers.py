"""Customer endpoints.

Staff with CUSTOMERS_READ list and open customers; CUSTOMERS_WRITE adds and edits
them; archiving needs CUSTOMERS_ARCHIVE. A customer reaches exactly one record -
their own - through /customers/me.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from serviceflow.api.deps import (
    ActiveUser,
    CustomersArchiver,
    CustomersReader,
    CustomersWriter,
    DbSession,
)
from serviceflow.core.pagination import Pagination, parse_sort
from serviceflow.schemas.customer import (
    CustomerCreate,
    CustomerRead,
    CustomerSelfUpdate,
    CustomerUpdate,
)
from serviceflow.schemas.envelope import DataResponse, PagedResponse, paged
from serviceflow.services import customers as customers_service

router = APIRouter(prefix="/customers", tags=["customers"])


def _read(db: DbSession, organization_id: uuid.UUID, customer) -> CustomerRead:  # type: ignore[no-untyped-def]
    history = customers_service.history_counts(db, organization_id, [customer.id])
    return CustomerRead.from_model(customer, history=history.get(customer.id))


@router.get("", response_model=PagedResponse[CustomerRead], summary="List customers")
def list_customers(
    current_user: CustomersReader,
    db: DbSession,
    pagination: Pagination,
    q: Annotated[
        str | None, Query(max_length=120, description="Name, email, phone or address")
    ] = None,
    include_archived: Annotated[bool, Query()] = False,
    sort: Annotated[str | None, Query(description="name | created_at, prefix - to reverse")] = None,
) -> PagedResponse[CustomerRead]:
    page = customers_service.list_customers(
        db,
        current_user.organization_id,
        pagination=pagination,
        q=q,
        include_archived=include_archived,
        sort=parse_sort(sort, allowed=customers_service.CUSTOMER_SORTS, default="name"),
    )
    history = customers_service.history_counts(
        db, current_user.organization_id, [customer.id for customer in page.items]
    )
    return paged(
        [CustomerRead.from_model(c, history=history.get(c.id)) for c in page.items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=page.total,
    )


@router.get("/me", response_model=DataResponse[CustomerRead], summary="Own customer profile")
def get_own_customer(current_user: ActiveUser, db: DbSession) -> DataResponse[CustomerRead]:
    customer = customers_service.get_customer_for_user(
        db, current_user.organization_id, current_user.user_id
    )
    return DataResponse[CustomerRead](data=_read(db, current_user.organization_id, customer))


@router.patch("/me", response_model=DataResponse[CustomerRead], summary="Update own profile")
def update_own_customer(
    payload: CustomerSelfUpdate, current_user: ActiveUser, db: DbSession
) -> DataResponse[CustomerRead]:
    """A customer edits their own name, phone and service address - nobody else's.

    The record is found from the verified caller, never from an id in the request.
    """
    own = customers_service.get_customer_for_user(
        db, current_user.organization_id, current_user.user_id
    )
    customer = customers_service.update_customer(
        db,
        current_user.organization_id,
        own.id,
        actor_user_id=current_user.user_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return DataResponse[CustomerRead](data=_read(db, current_user.organization_id, customer))


@router.get("/{customer_id}", response_model=DataResponse[CustomerRead], summary="Get a customer")
def get_customer(
    customer_id: uuid.UUID, current_user: CustomersReader, db: DbSession
) -> DataResponse[CustomerRead]:
    customer = customers_service.get_customer(db, current_user.organization_id, customer_id)
    return DataResponse[CustomerRead](data=_read(db, current_user.organization_id, customer))


@router.post(
    "",
    response_model=DataResponse[CustomerRead],
    status_code=status.HTTP_201_CREATED,
    summary="Add a customer",
)
def create_customer(
    payload: CustomerCreate, current_user: CustomersWriter, db: DbSession
) -> DataResponse[CustomerRead]:
    customer = customers_service.create_customer(
        db,
        current_user.organization_id,
        actor_user_id=current_user.user_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        address=payload.address,
        notes=payload.notes,
    )
    return DataResponse[CustomerRead](data=CustomerRead.from_model(customer))


@router.patch(
    "/{customer_id}", response_model=DataResponse[CustomerRead], summary="Update a customer"
)
def update_customer(
    customer_id: uuid.UUID, payload: CustomerUpdate, current_user: CustomersWriter, db: DbSession
) -> DataResponse[CustomerRead]:
    customer = customers_service.update_customer(
        db,
        current_user.organization_id,
        customer_id,
        actor_user_id=current_user.user_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return DataResponse[CustomerRead](data=_read(db, current_user.organization_id, customer))


@router.delete(
    "/{customer_id}",
    response_model=DataResponse[CustomerRead],
    summary="Archive a customer (soft delete)",
)
def archive_customer(
    customer_id: uuid.UUID, current_user: CustomersArchiver, db: DbSession
) -> DataResponse[CustomerRead]:
    """Archives rather than deletes, so past bookings still say who they were for."""
    customer = customers_service.archive_customer(
        db, current_user.organization_id, customer_id, actor_user_id=current_user.user_id
    )
    return DataResponse[CustomerRead](data=_read(db, current_user.organization_id, customer))
