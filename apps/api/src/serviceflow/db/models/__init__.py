"""Model registry. Import every model here so Alembic autogenerate sees them."""

from serviceflow.db.base import Base
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee, employee_services
from serviceflow.db.models.enums import (
    BookingStatus,
    JobStatus,
    MembershipStatus,
    NoteVisibility,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    PhotoType,
    Role,
)
from serviceflow.db.models.job import Job
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User
from serviceflow.db.models.vehicle import Vehicle

__all__ = [
    "Base",
    "Booking",
    "BookingStatus",
    "Customer",
    "Employee",
    "Job",
    "JobStatus",
    "MembershipStatus",
    "NoteVisibility",
    "NotificationChannel",
    "NotificationStatus",
    "NotificationType",
    "Organization",
    "OrganizationMembership",
    "PhotoType",
    "Role",
    "Service",
    "User",
    "Vehicle",
    "employee_services",
]
