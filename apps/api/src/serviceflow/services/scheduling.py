"""The seam where phase 4's scheduling engine plugs in.

Phase 3 only enforces what it can decide without an availability model: the
employee must belong to the organization, be active, and be qualified for the
service. Phase 4 adds weekly availability, date overrides, overlap detection and
the locking that makes concurrent assignment safe (PRD 9, 10).

Those checks belong *inside* `SchedulingPolicy.check_assignment`, which is called
from within the confirmation transaction with the live `Session`. A phase 4
implementation can therefore issue `SELECT ... FOR UPDATE` against employee jobs
and have it participate in the same transaction that writes the job - no caller
changes required.

To extend in phase 4: write a new policy class, and return it from
`get_scheduling_policy`. Do not scatter availability checks into the booking
service or the route handlers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from serviceflow.core.errors import ValidationFailed
from serviceflow.db.models.employee import Employee
from serviceflow.db.models.service import Service


@dataclass(frozen=True, slots=True)
class AssignmentRequest:
    """Everything a scheduling decision needs, so the signature survives phase 4."""

    organization_id: uuid.UUID
    employee: Employee
    service: Service
    start: datetime
    end: datetime
    # Set when rescheduling or reassigning, so a job is not treated as its own conflict.
    exclude_job_id: uuid.UUID | None = None


class SchedulingPolicy(Protocol):
    def check_assignment(self, db: Session, request: AssignmentRequest) -> None:
        """Raise an AppError if this employee must not take this work."""
        ...


class QualificationPolicy:
    """Phase 3 rules: the employee must be active and qualified.

    Phase 4 will subclass or replace this to add availability and overlap checks.
    """

    def check_assignment(self, db: Session, request: AssignmentRequest) -> None:
        employee = request.employee
        service = request.service

        if employee.organization_id != request.organization_id:
            raise ValidationFailed(
                "That employee isn't part of this organization.",
                details={"fields": {"employee_id": "Unknown employee."}},
            )

        if not employee.active:
            raise ValidationFailed(
                f"{employee.user.full_name} is deactivated and can't be assigned work.",
                details={"fields": {"employee_id": "Employee is not active."}},
            )

        qualified = {qualification.id for qualification in employee.services}
        if service.id not in qualified:
            raise ValidationFailed(
                f"{employee.user.full_name} isn't qualified for {service.name}.",
                details={"fields": {"employee_id": "Not qualified for this service."}},
            )


_policy: SchedulingPolicy = QualificationPolicy()


def get_scheduling_policy() -> SchedulingPolicy:
    return _policy


def set_scheduling_policy(policy: SchedulingPolicy) -> None:
    """Swap the policy. Phase 4 uses this; tests use it to assert the seam works."""
    global _policy
    _policy = policy
