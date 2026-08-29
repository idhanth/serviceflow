from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from serviceflow.db.models.employee import Employee
from serviceflow.schemas.common import UserSummary


class EmployeeServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    duration_minutes: int


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user: UserSummary
    job_title: str
    active: bool
    services: list[EmployeeServiceSummary]

    @classmethod
    def from_model(cls, employee: Employee) -> EmployeeRead:
        return cls(
            id=employee.id,
            user=UserSummary.model_validate(employee.user),
            job_title=employee.job_title,
            active=employee.active,
            services=[
                EmployeeServiceSummary.model_validate(service)
                for service in sorted(employee.services, key=lambda s: s.name)
            ],
        )


class EmployeeCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    job_title: str = Field(default="Technician", min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    service_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    job_title: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    active: bool | None = None
    service_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
