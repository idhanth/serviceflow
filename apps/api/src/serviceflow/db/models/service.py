from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from serviceflow.db.base import Base, Timestamps, UUIDPrimaryKey
from serviceflow.db.models.mixins import OrganizationScoped

if TYPE_CHECKING:
    from serviceflow.db.models.employee import Employee


class Service(UUIDPrimaryKey, OrganizationScoped, Timestamps, Base):
    """An offering with a price and a duration. Duration drives booking end times."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        # Target for the composite (organization_id, service_id) foreign keys.
        UniqueConstraint("organization_id", "id"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("base_price >= 0", name="price_not_negative"),
        Index("ix_services_organization_id_active", "organization_id", "active"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    image_url: Mapped[str | None] = mapped_column(Text)

    employees: Mapped[list[Employee]] = relationship(
        secondary="employee_services",
        primaryjoin="Service.id == EmployeeService.service_id",
        secondaryjoin="Employee.id == EmployeeService.employee_id",
        viewonly=True,
    )
