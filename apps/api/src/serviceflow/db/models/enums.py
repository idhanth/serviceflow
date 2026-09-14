"""Domain enumerations. Names are persisted, so never rename a member casually."""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    """A person's role inside one tenant. Permissions live in auth/permissions.py.

    The seventh role, Platform Admin, is deliberately not a member of this enum:
    it is not held *inside* a tenant, so it is a flag on the user
    (`users.is_platform_admin`) rather than a membership row.
    """

    OWNER = "OWNER"
    MANAGER = "MANAGER"
    DISPATCHER = "DISPATCHER"
    TECHNICIAN = "TECHNICIAN"
    CUSTOMER = "CUSTOMER"
    ANALYST = "ANALYST"


class MembershipStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"


class BookingStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class JobStatus(enum.StrEnum):
    NEW = "NEW"  # created with its booking, nobody assigned yet
    SCHEDULED = "SCHEDULED"  # a technician holds the time
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PhotoType(enum.StrEnum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    OTHER = "OTHER"


class NoteVisibility(enum.StrEnum):
    INTERNAL = "INTERNAL"
    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE"


class NotificationType(enum.StrEnum):
    BOOKING_CREATED = "BOOKING_CREATED"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    BOOKING_REJECTED = "BOOKING_REJECTED"
    BOOKING_RESCHEDULED = "BOOKING_RESCHEDULED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    APPOINTMENT_REMINDER = "APPOINTMENT_REMINDER"
    JOB_STARTED = "JOB_STARTED"
    JOB_COMPLETED = "JOB_COMPLETED"


class NotificationChannel(enum.StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class NotificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


class AuditAction(enum.StrEnum):
    """State-changing actions worth remembering (PRD 35).

    Reads are deliberately absent: an audit trail full of page views is one
    nobody reads. Every member here is a mutation someone may later need to
    explain.
    """

    BOOKING_CREATED = "BOOKING_CREATED"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    BOOKING_REJECTED = "BOOKING_REJECTED"
    BOOKING_RESCHEDULED = "BOOKING_RESCHEDULED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"

    JOB_ASSIGNED = "JOB_ASSIGNED"
    JOB_REASSIGNED = "JOB_REASSIGNED"
    JOB_STARTED = "JOB_STARTED"
    JOB_COMPLETED = "JOB_COMPLETED"
    JOB_CANCELLED = "JOB_CANCELLED"

    NOTE_ADDED = "NOTE_ADDED"
    NOTE_DELETED = "NOTE_DELETED"
    PHOTO_DELETED = "PHOTO_DELETED"

    CUSTOMER_CREATED = "CUSTOMER_CREATED"
    CUSTOMER_UPDATED = "CUSTOMER_UPDATED"
    CUSTOMER_ARCHIVED = "CUSTOMER_ARCHIVED"
    EMPLOYEE_CREATED = "EMPLOYEE_CREATED"
    EMPLOYEE_UPDATED = "EMPLOYEE_UPDATED"
    EMPLOYEE_DEACTIVATED = "EMPLOYEE_DEACTIVATED"
    EMPLOYEE_REACTIVATED = "EMPLOYEE_REACTIVATED"

    SERVICE_CREATED = "SERVICE_CREATED"
    SERVICE_UPDATED = "SERVICE_UPDATED"
    SERVICE_RETIRED = "SERVICE_RETIRED"

    USER_INVITED = "USER_INVITED"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
    MEMBER_SUSPENDED = "MEMBER_SUSPENDED"
    MEMBER_REACTIVATED = "MEMBER_REACTIVATED"
    ORGANIZATION_UPDATED = "ORGANIZATION_UPDATED"
    TENANT_CREATED = "TENANT_CREATED"
    AVAILABILITY_UPDATED = "AVAILABILITY_UPDATED"
    AVAILABILITY_OVERRIDE_SET = "AVAILABILITY_OVERRIDE_SET"
    AVAILABILITY_OVERRIDE_REMOVED = "AVAILABILITY_OVERRIDE_REMOVED"
