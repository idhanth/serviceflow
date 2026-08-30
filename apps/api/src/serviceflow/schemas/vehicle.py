from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from serviceflow.db.models.vehicle import Vehicle

MIN_YEAR = 1900
MAX_YEAR = 2100


class VehicleOwner(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    full_name: str


class VehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    year: int
    make: str
    model: str
    color: str | None = None
    license_plate: str | None = None
    notes: str | None = None
    display_name: str
    archived: bool = False
    owner: VehicleOwner | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, vehicle: Vehicle, *, include_owner: bool = False) -> VehicleRead:
        return cls(
            id=vehicle.id,
            customer_id=vehicle.customer_id,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            color=vehicle.color,
            license_plate=vehicle.license_plate,
            notes=vehicle.notes,
            display_name=vehicle.display_name,
            archived=vehicle.archived,
            owner=(
                VehicleOwner(
                    customer_id=vehicle.customer_id,
                    full_name=vehicle.customer.user.full_name,
                )
                if include_owner
                else None
            ),
            created_at=vehicle.created_at,
        )


class VehicleCreate(BaseModel):
    # Admins name the owner; a customer's own id is derived from their session.
    customer_id: uuid.UUID | None = None
    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    license_plate: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class VehicleUpdate(BaseModel):
    year: int | None = Field(default=None, ge=MIN_YEAR, le=MAX_YEAR)
    make: str | None = Field(default=None, min_length=1, max_length=60)
    model: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, max_length=40)
    license_plate: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
