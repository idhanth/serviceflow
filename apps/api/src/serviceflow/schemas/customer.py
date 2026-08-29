from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from serviceflow.db.models.customer import Customer
from serviceflow.schemas.common import UserSummary


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user: UserSummary
    notes: str | None = None
    vehicle_count: int = 0
    created_at: datetime

    @classmethod
    def from_model(cls, customer: Customer, *, vehicle_count: int = 0) -> CustomerRead:
        return cls(
            id=customer.id,
            user=UserSummary.model_validate(customer.user),
            notes=customer.notes,
            vehicle_count=vehicle_count,
            created_at=customer.created_at,
        )


class CustomerCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class CustomerUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
