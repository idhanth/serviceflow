"""Unit tests for the transition tables - no HTTP, no database."""

from __future__ import annotations

import pytest

from serviceflow.core.errors import InvalidStateTransition
from serviceflow.db.models.booking import Booking
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.services.state_machine import (
    BOOKING_TRANSITIONS,
    JOB_TRANSITIONS,
    can_transition_job,
    transition_booking,
    transition_job,
)


def _booking(status: BookingStatus) -> Booking:
    booking = Booking()
    booking.status = status
    return booking


def _job(status: JobStatus) -> Job:
    job = Job()
    job.status = status
    return job


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (BookingStatus.PENDING, BookingStatus.CONFIRMED),
        (BookingStatus.PENDING, BookingStatus.REJECTED),
        (BookingStatus.PENDING, BookingStatus.CANCELLED),
        (BookingStatus.CONFIRMED, BookingStatus.CANCELLED),
    ],
)
def test_allowed_booking_transitions(start: BookingStatus, target: BookingStatus) -> None:
    booking = _booking(start)
    transition_booking(booking, target)
    assert booking.status is target


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (BookingStatus.CONFIRMED, BookingStatus.PENDING),
        (BookingStatus.CONFIRMED, BookingStatus.CONFIRMED),
        (BookingStatus.REJECTED, BookingStatus.CONFIRMED),
        (BookingStatus.CANCELLED, BookingStatus.PENDING),
        (BookingStatus.CANCELLED, BookingStatus.CONFIRMED),
    ],
)
def test_refused_booking_transitions(start: BookingStatus, target: BookingStatus) -> None:
    booking = _booking(start)
    with pytest.raises(InvalidStateTransition):
        transition_booking(booking, target)
    assert booking.status is start


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (JobStatus.SCHEDULED, JobStatus.IN_PROGRESS),
        (JobStatus.SCHEDULED, JobStatus.CANCELLED),
        (JobStatus.IN_PROGRESS, JobStatus.COMPLETED),
    ],
)
def test_allowed_job_transitions(start: JobStatus, target: JobStatus) -> None:
    job = _job(start)
    transition_job(job, target)
    assert job.status is target


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (JobStatus.SCHEDULED, JobStatus.COMPLETED),
        (JobStatus.IN_PROGRESS, JobStatus.SCHEDULED),
        (JobStatus.IN_PROGRESS, JobStatus.CANCELLED),
        (JobStatus.COMPLETED, JobStatus.IN_PROGRESS),
        (JobStatus.COMPLETED, JobStatus.SCHEDULED),
        (JobStatus.COMPLETED, JobStatus.CANCELLED),
        (JobStatus.CANCELLED, JobStatus.SCHEDULED),
        (JobStatus.CANCELLED, JobStatus.IN_PROGRESS),
    ],
)
def test_refused_job_transitions(start: JobStatus, target: JobStatus) -> None:
    job = _job(start)
    with pytest.raises(InvalidStateTransition):
        transition_job(job, target)
    assert job.status is start


def test_terminal_states_have_no_way_out() -> None:
    """Nothing may leave COMPLETED, CANCELLED or REJECTED."""
    assert JOB_TRANSITIONS[JobStatus.COMPLETED] == frozenset()
    assert JOB_TRANSITIONS[JobStatus.CANCELLED] == frozenset()
    assert BOOKING_TRANSITIONS[BookingStatus.REJECTED] == frozenset()
    assert BOOKING_TRANSITIONS[BookingStatus.CANCELLED] == frozenset()


def test_every_status_is_covered_by_a_transition_table() -> None:
    """A new status must not silently become unreachable by the state machine."""
    assert set(BOOKING_TRANSITIONS) == set(BookingStatus)
    assert set(JOB_TRANSITIONS) == set(JobStatus)


def test_the_error_names_both_states() -> None:
    job = _job(JobStatus.COMPLETED)
    with pytest.raises(InvalidStateTransition) as raised:
        transition_job(job, JobStatus.IN_PROGRESS)
    assert raised.value.details == {"from": "completed", "to": "in progress"}
    assert raised.value.status_code == 409


def test_read_only_check_does_not_mutate() -> None:
    job = _job(JobStatus.SCHEDULED)
    assert can_transition_job(job, JobStatus.IN_PROGRESS) is True
    assert can_transition_job(job, JobStatus.COMPLETED) is False
    assert job.status is JobStatus.SCHEDULED
