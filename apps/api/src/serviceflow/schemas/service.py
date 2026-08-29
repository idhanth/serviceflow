from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from serviceflow.db.models.service import Service

MAX_DURATION_MINUTES = 24 * 60


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    base_price: Decimal
    duration_minutes: int
    active: bool
    image_url: str | None = None
    employee_count: int = 0

    @classmethod
    def from_model(cls, service: Service) -> ServiceRead:
        return cls(
            id=service.id,
            name=service.name,
            description=service.description,
            base_price=service.base_price,
            duration_minutes=service.duration_minutes,
            active=service.active,
            image_url=service.image_url,
            employee_count=len(service.employees),
        )


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    base_price: Decimal = Field(ge=0, le=Decimal("99999.99"), decimal_places=2)
    duration_minutes: int = Field(gt=0, le=MAX_DURATION_MINUTES)
    image_url: str | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Enter a service name.")
        return stripped


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    base_price: Decimal | None = Field(default=None, ge=0, le=Decimal("99999.99"))
    duration_minutes: int | None = Field(default=None, gt=0, le=MAX_DURATION_MINUTES)
    active: bool | None = None
    image_url: str | None = None
