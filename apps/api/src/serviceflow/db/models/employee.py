from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
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


class EmployeeService(Base):
    """Which services an employee is qualified to perform.

    Carries `organization_id` so both halves can be composite foreign keys: a
    Tenant A technician can never be recorded as qualified for a Tenant B service.
    """

    __tablename__ = "employee_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "service_id"],
            ["services.organization_id", "services.id"],
            ondelete="CASCADE",
        ),
        Index("ix_employee_services_service_id", "service_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    service_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


class Employee(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        UniqueConstraint("organization_id", "id"),
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
    service_links: Mapped[list[EmployeeService]] = relationship(
        cascade="all, delete-orphan",
        primaryjoin="Employee.id == EmployeeService.employee_id",
        foreign_keys="EmployeeService.employee_id",
    )
    # Read through the links; written with `set_qualifications` in services/employees.py.
    services: Mapped[list[Service]] = relationship(
        secondary="employee_services",
        primaryjoin="Employee.id == EmployeeService.employee_id",
        secondaryjoin="Service.id == EmployeeService.service_id",
        viewonly=True,
    )
    availability: Mapped[list[EmployeeAvailability]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        primaryjoin="Employee.id == EmployeeAvailability.employee_id",
        foreign_keys="EmployeeAvailability.employee_id",
    )
    availability_overrides: Mapped[list[AvailabilityOverride]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
        primaryjoin="Employee.id == AvailabilityOverride.employee_id",
        foreign_keys="AvailabilityOverride.employee_id",
    )
