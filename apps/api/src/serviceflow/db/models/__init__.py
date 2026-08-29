"""Model registry. Import every model here so Alembic autogenerate sees them."""

from serviceflow.db.base import Base
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
from serviceflow.db.models.membership import OrganizationMembership
from serviceflow.db.models.organization import Organization
from serviceflow.db.models.user import User

__all__ = [
    "Base",
    "BookingStatus",
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
    "User",
]
