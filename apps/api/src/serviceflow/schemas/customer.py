from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from serviceflow.db.models.customer import Customer
from serviceflow.schemas.common import UserSummary


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user: UserSummary
    address: str | None = None
    notes: str | None = None
    archived: bool = False
    booking_count: int = 0
    completed_jobs: int = 0
    last_service_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_model(
        cls, customer: Customer, *, history: dict[str, Any] | None = None
    ) -> CustomerRead:
        history = history or {}
        return cls(
            id=customer.id,
            user=UserSummary.model_validate(customer.user),
            address=customer.address,
            notes=customer.notes,
            archived=customer.archived,
            booking_count=history.get("booking_count", 0),
            completed_jobs=history.get("completed_jobs", 0),
            last_service_at=history.get("last_service_at"),
            created_at=customer.created_at,
        )


class CustomerCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)


class CustomerUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)


class CustomerSelfUpdate(BaseModel):
    """What a customer may change about themselves. Internal notes are not on the list."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
