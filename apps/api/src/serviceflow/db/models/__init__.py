"""Model registry. Import every model here so Alembic autogenerate sees them."""

from serviceflow.db.base import Base
from serviceflow.db.models.audit import AuditLog
from serviceflow.db.models.availability import (
    AvailabilityOverride,
    EmployeeAvailability,
)
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.customer import Customer
from serviceflow.db.models.employee import Employee, EmployeeService
from serviceflow.db.models.enums import (
    AuditAction,
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
from serviceflow.db.models.idempotency import IdempotencyRecord
from serviceflow.db.models.job import Job
from serviceflow.db.models.job_note import JobNote
from serviceflow.db.models.job_photo import JobPhoto
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.notification import Notification
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.service import Service
from serviceflow.db.models.user import User

__all__ = [
    "AuditAction",
    "AuditLog",
    "AvailabilityOverride",
    "Base",
    "Booking",
    "BookingStatus",
    "Customer",
    "Employee",
    "EmployeeAvailability",
    "EmployeeService",
    "IdempotencyRecord",
    "Job",
    "JobNote",
    "JobPhoto",
    "JobStatus",
    "MembershipStatus",
    "NoteVisibility",
    "Notification",
    "NotificationChannel",
    "NotificationStatus",
    "NotificationType",
    "Organization",
    "OrganizationMembership",
    "PhotoType",
    "Role",
    "Service",
    "User",
]
