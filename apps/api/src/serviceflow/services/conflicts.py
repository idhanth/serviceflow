"""Overlap detection and the locking that makes it safe under concurrency.

Two independent mechanisms guard the "no double-booked employee" invariant:

  1. `lock_employee_schedule` takes a transaction-scoped advisory lock keyed on
     the employee, so two requests assigning the same person serialise instead of
     interleaving their check-then-write. This is what turns a race into a clean
     409 with a message naming the clashing job.
  2. `jobs` carries a PostgreSQL exclusion constraint over
     (employee_id, tstzrange(scheduled_start, scheduled_end)) for non-cancelled
     rows. Even a future code path that forgets the lock cannot write an overlap;
     the database refuses it.

See docs/adr-0004 for why both, rather than either alone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from serviceflow.db.models.enums import JobStatus
from serviceflow.db.models.job import Job

# Raised by the exclusion constraint below; matched by name so an unrelated
# integrity error is never mistaken for a scheduling clash.
OVERLAP_CONSTRAINT = "jobs_no_overlapping_assignments"


def lock_employee_schedule(db: Session, employee_id: uuid.UUID) -> None:
    """Serialise schedule changes for one employee for the rest of this transaction.

    Advisory rather than row-level: the rows that would conflict may not exist
    yet, so there is nothing to lock with SELECT ... FOR UPDATE. The lock is
    released automatically when the transaction ends, including on rollback.

    hashtext() maps the UUID onto 32 bits, so two employees can in principle share
    a lock key. That only ever costs a little serialisation - never correctness.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": str(employee_id)})


def overlapping_jobs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude_job_id: uuid.UUID | None = None,
) -> list[Job]:
    """Non-cancelled jobs for this employee that overlap [start, end).

    The rule is PRD 9's exactly:  new_start < existing_end AND new_end > existing_start

    Adjacent appointments therefore do not conflict: 10:00-12:00 and 12:00-14:00
    both satisfy neither strict inequality at the boundary. Cancelled jobs are
    excluded because cancelling is what frees a slot; completed jobs still block,
    since that time really was spent.
    """
    statement = select(Job).where(
        Job.organization_id == organization_id,
        Job.employee_id == employee_id,
        Job.status != JobStatus.CANCELLED,
        Job.scheduled_start < end,
        Job.scheduled_end > start,
    )
    if exclude_job_id is not None:
        statement = statement.where(Job.id != exclude_job_id)
    return list(db.scalars(statement).unique())


def is_overlap_violation(error: Exception) -> bool:
    """True when an IntegrityError came from the scheduling exclusion constraint."""
    return OVERLAP_CONSTRAINT in str(getattr(error, "orig", error))
