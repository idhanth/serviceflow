from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.availability import (
        AvailabilityOverride,
        EmployeeAvailability,
    )
    from serviceflow.db.models.service import Service
    from serviceflow.db.models.user import User


employee_services = Table(
    "employee_services",
    Base.metadata,
    Column(
        "employee_id",
        PGUUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        PGUUID(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
"""Which services an employee is qualified to perform (PRD 7, 11)."""


class Employee(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        Index("ix_employees_organization_id_active", "organization_id", "active"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_title: Mapped[str] = mapped_column(String(120), nullable=False, default="Technician")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(lazy="joined")
    services: Mapped[list[Service]] = relationship(
        secondary=employee_services, back_populates="employees"
    )
    availability: Mapped[list[EmployeeAvailability]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    availability_overrides: Mapped[list[AvailabilityOverride]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
