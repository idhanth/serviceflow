"""The only place booking and job status changes are decided (PRD 12).

Every transition in the application goes through `transition_booking` or
`transition_job`. Nothing assigns `.status` directly, so an illegal move cannot
be introduced by a new call site forgetting a check.
"""

from __future__ import annotations

from serviceflow.core.errors import InvalidStateTransition
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job

BOOKING_TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    BookingStatus.PENDING: frozenset(
        {BookingStatus.CONFIRMED, BookingStatus.REJECTED, BookingStatus.CANCELLED}
    ),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    # Terminal: a decided booking is never reopened. A customer who changes their
    # mind makes a new booking.
    BookingStatus.REJECTED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
}

JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.ASSIGNED: frozenset({JobStatus.IN_PROGRESS, JobStatus.CANCELLED}),
    JobStatus.IN_PROGRESS: frozenset({JobStatus.COMPLETED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

_BOOKING_LABELS = {
    BookingStatus.PENDING: "pending",
    BookingStatus.CONFIRMED: "confirmed",
    BookingStatus.REJECTED: "rejected",
    BookingStatus.CANCELLED: "cancelled",
}

_JOB_LABELS = {
    JobStatus.ASSIGNED: "assigned",
    JobStatus.IN_PROGRESS: "in progress",
    JobStatus.COMPLETED: "completed",
    JobStatus.CANCELLED: "cancelled",
}


def _refuse(current: str, target: str, noun: str) -> InvalidStateTransition:
    return InvalidStateTransition(
        f"This {noun} is {current}, so it can't be moved to {target}.",
        details={"from": current, "to": target},
    )


def transition_booking(booking: Booking, target: BookingStatus) -> None:
    """Move a booking, or raise 409 INVALID_STATE_TRANSITION."""
    if target not in BOOKING_TRANSITIONS[booking.status]:
        raise _refuse(_BOOKING_LABELS[booking.status], _BOOKING_LABELS[target], "booking")
    booking.status = target


def transition_job(job: Job, target: JobStatus) -> None:
    """Move a job, or raise 409 INVALID_STATE_TRANSITION."""
    if target not in JOB_TRANSITIONS[job.status]:
        raise _refuse(_JOB_LABELS[job.status], _JOB_LABELS[target], "job")
    job.status = target


def can_transition_booking(booking: Booking, target: BookingStatus) -> bool:
    """Read-only check, for shaping UI affordances without attempting the move."""
    return target in BOOKING_TRANSITIONS[booking.status]


def can_transition_job(job: Job, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS[job.status]
