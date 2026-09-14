"""The database's own tenant and booking guarantees, with the application out of the way.

Each test writes rows directly - no service layer, no permission checks - and
expects PostgreSQL to refuse the ones that would break an invariant. If any of
these passed, a bug anywhere above the database could corrupt the data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from serviceflow.db.models.booking import Booking
from serviceflow.db.models.employee import EmployeeService
from serviceflow.db.models.enums import BookingStatus, JobStatus
from serviceflow.db.models.job import Job
from serviceflow.db.models.organization import Organization
from tests.conftest import (
    booking_setup,
    make_booking,
    make_organization,
)

START = datetime(2031, 3, 4, 15, 0, tzinfo=UTC)


@pytest.fixture()
def tenants(db: Session) -> tuple[dict, dict]:  # type: ignore[type-arg]
    north = make_organization(db, name="Northside Home Services")
    harbor = make_organization(db, name="Harbor Plumbing")
    return (
        {"org": north, **booking_setup(db, north)},
        {"org": harbor, **booking_setup(db, harbor)},
    )


def _refused(db: Session, row: object, constraint: str) -> None:
    db.add(row)
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()
    db.rollback()


def _booking(org: Organization, customer_id, service_id, start=START, status=BookingStatus.PENDING):  # type: ignore[no-untyped-def]
    return Booking(
        organization_id=org.id,
        customer_id=customer_id,
        service_id=service_id,
        requested_start=start,
        requested_end=start + timedelta(hours=2),
        status=status,
    )


def test_a_booking_cannot_pair_a_customer_with_another_tenants_service(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, harbor = tenants
    _refused(
        db,
        _booking(north["org"], north["customer"].id, harbor["service"].id),
        "fk_bookings_organization_id_services",
    )


def test_a_booking_cannot_use_another_tenants_customer(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, harbor = tenants
    _refused(
        db,
        _booking(north["org"], harbor["customer"].id, north["service"].id),
        "fk_bookings_organization_id_customers",
    )


def test_a_job_cannot_assign_another_tenants_technician(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, harbor = tenants
    booking = make_booking(db, north["org"], north["customer"], north["service"], start=START)
    job = db.query(Job).filter_by(booking_id=booking.id).one()
    job.employee_id = harbor["employee"].id
    job.status = JobStatus.SCHEDULED
    with pytest.raises(IntegrityError, match="fk_jobs_organization_id_employees"):
        db.commit()
    db.rollback()


def test_a_technician_cannot_be_qualified_for_another_tenants_service(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, harbor = tenants
    _refused(
        db,
        EmployeeService(
            organization_id=north["org"].id,
            employee_id=north["employee"].id,
            service_id=harbor["service"].id,
        ),
        "fk_employee_services_organization_id_services",
    )


def test_an_exact_duplicate_open_booking_is_refused(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, _ = tenants
    db.add(_booking(north["org"], north["customer"].id, north["service"].id))
    db.commit()
    _refused(
        db,
        _booking(north["org"], north["customer"].id, north["service"].id),
        "uq_bookings_no_duplicate_open",
    )


def test_a_cancelled_booking_does_not_block_rebooking_the_same_slot(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, _ = tenants
    db.add(
        _booking(
            north["org"], north["customer"].id, north["service"].id, status=BookingStatus.CANCELLED
        )
    )
    db.add(_booking(north["org"], north["customer"].id, north["service"].id))
    db.commit()


def _assign(db: Session, booking: Booking, employee_id, status=JobStatus.SCHEDULED) -> None:  # type: ignore[no-untyped-def]
    job = db.query(Job).filter_by(booking_id=booking.id).one()
    job.employee_id = employee_id
    job.status = status


def test_overlapping_jobs_for_one_technician_are_refused(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, _ = tenants
    first = make_booking(db, north["org"], north["customer"], north["service"], start=START)
    second = make_booking(
        db, north["org"], north["customer"], north["service"], start=START + timedelta(minutes=30)
    )
    _assign(db, first, north["employee"].id)
    db.commit()
    _assign(db, second, north["employee"].id)
    with pytest.raises(IntegrityError, match="jobs_no_overlapping_assignments"):
        db.commit()
    db.rollback()


def test_adjacent_and_cancelled_jobs_do_not_conflict(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, _ = tenants
    service = north["service"]  # 150 minutes
    first = make_booking(db, north["org"], north["customer"], service, start=START)
    adjacent = make_booking(
        db, north["org"], north["customer"], service, start=START + timedelta(minutes=150)
    )
    _assign(db, first, north["employee"].id)
    _assign(db, adjacent, north["employee"].id)
    db.commit()

    # A cancelled job keeps its technician for the record but no longer holds the time.
    _assign(db, first, north["employee"].id, status=JobStatus.CANCELLED)
    db.commit()
    # Overlaps only the cancelled job (starts an hour before it), not the adjacent one.
    overlapping = make_booking(
        db, north["org"], north["customer"], service, start=START - timedelta(minutes=60)
    )
    _assign(db, overlapping, north["employee"].id)
    db.commit()


def test_a_new_job_cannot_have_a_technician_and_a_scheduled_one_must(
    db: Session, tenants: tuple[dict, dict]
) -> None:
    north, _ = tenants
    booking = make_booking(db, north["org"], north["customer"], north["service"], start=START)
    job = db.query(Job).filter_by(booking_id=booking.id).one()

    job.employee_id = north["employee"].id  # still NEW
    with pytest.raises(IntegrityError, match="ck_jobs_new_jobs_unassigned"):
        db.commit()
    db.rollback()

    job = db.query(Job).filter_by(booking_id=booking.id).one()
    job.status = JobStatus.SCHEDULED  # but nobody assigned
    with pytest.raises(IntegrityError, match="ck_jobs_active_jobs_assigned"):
        db.commit()
    db.rollback()
