"""Domain enumerations. Names are persisted, so never rename a member casually."""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    EMPLOYEE = "EMPLOYEE"
    ADMIN = "ADMIN"


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
    ASSIGNED = "ASSIGNED"
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
