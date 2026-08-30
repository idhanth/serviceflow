"""Test fixtures. Every test runs against a dedicated database, never the dev one."""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from datetime import date as dt_date
from datetime import time as dt_time
from decimal import Decimal

import pytest

# Settings are cached at import time, so the test environment must be set first.
_DEV_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost:5433/serviceflow")
TEST_DATABASE_URL = _DEV_URL.rsplit("/", 1)[0] + "/serviceflow_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-definitely-long-enough-123")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/1")

# Object storage: a separate bucket on the same local MinIO the dev stack uses,
# so upload tests exercise a real S3 API rather than a stub.
os.environ.setdefault("S3_BUCKET", "serviceflow-test-media")
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("S3_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "serviceflow")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "serviceflow-dev-secret")

# Celery: the default suite queues onto an in-memory transport so no test pays
# for a broker round trip. The tasks themselves are exercised by calling them
# directly, and tests/test_celery_integration.py runs a real worker against real
# Redis to prove the wiring.
os.environ.setdefault("SERVICEFLOW_BROKER_URL", "memory://")
os.environ.setdefault("SERVICEFLOW_RESULT_BACKEND", "cache+memory://")
# Email goes to the local MailPit, which is a real SMTP server.
# Rate limiting is off by default: every test signs in from the same identity,
# so a shared limiter would exhaust itself. tests/test_rate_limiting.py turns it
# on explicitly and exercises it against real Redis.
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("EMAIL_PROVIDER", "smtp")
os.environ.setdefault("SMTP_HOST", "127.0.0.1")
os.environ.setdefault("SMTP_PORT", "1025")

import pathlib  # noqa: E402

import httpx  # noqa: E402
import psycopg  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from serviceflow.auth.passwords import hash_password  # noqa: E402
from serviceflow.db.models import Base  # noqa: E402
from serviceflow.db.models.availability import (  # noqa: E402
    AvailabilityOverride,
    EmployeeAvailability,
)
from serviceflow.db.models.booking import Booking  # noqa: E402
from serviceflow.db.models.customer import Customer  # noqa: E402
from serviceflow.db.models.employee import Employee  # noqa: E402
from serviceflow.db.models.enums import (  # noqa: E402
    BookingStatus,
    JobStatus,
    MembershipStatus,
    NoteVisibility,
    Role,
)
from serviceflow.db.models.job import Job  # noqa: E402
from serviceflow.db.models.job_note import JobNote  # noqa: E402
from serviceflow.db.models.membership import OrganizationMembership  # noqa: E402
from serviceflow.db.models.notification import Notification  # noqa: E402
from serviceflow.db.models.organization import Organization  # noqa: E402
from serviceflow.db.models.service import Service  # noqa: E402
from serviceflow.db.models.user import User  # noqa: E402
from serviceflow.db.models.vehicle import Vehicle  # noqa: E402
from serviceflow.db.session import get_session_factory, reset_engine  # noqa: E402
from serviceflow.main import create_app  # noqa: E402
from serviceflow.services.storage import (  # noqa: E402
    get_object_storage,
    reset_object_storage,
)

TEST_PASSWORD = "test-password-123"


def _admin_dsn() -> str:
    return (
        TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0]
        + "/postgres"
    )


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Build the test schema by running the real migrations.

    Not `Base.metadata.create_all`: the scheduling guarantee lives in a
    PostgreSQL exclusion constraint and the btree_gist extension, neither of
    which SQLAlchemy metadata knows about. Tests have to run against the schema
    that actually ships, or the concurrency tests would pass against a database
    missing the very constraint they exist to prove.
    """
    name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')

    # Start from nothing so a stale schema can never mask a broken migration.
    plain_dsn = TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(plain_dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    config = Config(str(pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(config, "head")

    reset_engine()
    yield
    reset_engine()


@pytest.fixture(scope="session", autouse=True)
def _bucket() -> Iterator[None]:
    """Make sure the test bucket exists before any upload test runs."""
    reset_object_storage()
    get_object_storage().ensure_bucket()
    yield


@pytest.fixture()
def db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def _clean_tables(db: Session) -> Iterator[None]:
    """Reset between tests with one TRUNCATE.

    Not per-table DELETE: `audit_logs` carries an append-only trigger that
    rejects DELETE by design, and TRUNCATE is both permitted and faster.
    """
    yield
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.commit()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def make_organization(db: Session, *, name: str = "Gleam Auto") -> Organization:
    slug = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"
    org = Organization(name=name, slug=slug, email=f"{slug}@example.com", timezone="UTC")
    db.add(org)
    db.commit()
    return org


def make_user(
    db: Session,
    organization: Organization,
    *,
    role: Role,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str = "Tester",
) -> User:
    email = email or f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        auth_provider_id=f"dev|{email}",
        email=email,
        first_name=first_name or role.value.title(),
        last_name=last_name,
        password_hash=hash_password(TEST_PASSWORD),
    )
    db.add(user)
    db.flush()
    db.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
    )
    db.commit()
    return user


@pytest.fixture()
def organization(db: Session) -> Organization:
    return make_organization(db)


@pytest.fixture()
def admin(db: Session, organization: Organization) -> User:
    return make_user(db, organization, role=Role.ADMIN)


def auth_headers(
    client: TestClient, user: User, organization: Organization | None = None
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if organization is not None:
        headers["X-Organization-Id"] = str(organization.id)
    return headers


# ---------------------------------------------------------------- phase 2 factories


def make_service(
    db: Session,
    organization: Organization,
    *,
    name: str = "Full Detail",
    price: str = "310.00",
    duration_minutes: int = 240,
    active: bool = True,
) -> Service:
    service = Service(
        organization_id=organization.id,
        name=name,
        description=f"{name} description",
        base_price=Decimal(price),
        duration_minutes=duration_minutes,
        active=active,
    )
    db.add(service)
    db.commit()
    return service


def make_customer(
    db: Session,
    organization: Organization,
    *,
    email: str | None = None,
    first_name: str = "Casey",
    last_name: str = "Customer",
    notes: str | None = None,
) -> Customer:
    user = make_user(
        db,
        organization,
        role=Role.CUSTOMER,
        email=email,
        first_name=first_name,
        last_name=last_name,
    )
    customer = Customer(organization_id=organization.id, user_id=user.id, notes=notes)
    db.add(customer)
    db.commit()
    return customer


def make_employee(
    db: Session,
    organization: Organization,
    *,
    email: str | None = None,
    job_title: str = "Detailer",
    active: bool = True,
    services: list[Service] | None = None,
    always_available: bool = True,
) -> Employee:
    """Create an employee, available around the clock unless told otherwise.

    Phase 4 enforces working hours, so a schedule-less employee can no longer be
    assigned anything. Tests that are not about availability get a full week by
    default; tests that are about it pass `always_available=False` and build the
    schedule they mean to exercise.
    """
    user = make_user(
        db, organization, role=Role.EMPLOYEE, email=email, first_name="Erin", last_name="Employee"
    )
    employee = Employee(
        organization_id=organization.id, user_id=user.id, job_title=job_title, active=active
    )
    employee.services = services or []
    db.add(employee)
    db.commit()

    if always_available:
        set_weekly_availability(db, employee, days=range(7), start="00:00", end="23:59")
    return employee


def set_weekly_availability(
    db: Session,
    employee: Employee,
    *,
    days: object,
    start: str,
    end: str,
) -> None:
    """Add one recurring window on each of `days` (Monday 0 ... Sunday 6)."""
    for day in days:  # type: ignore[attr-defined]
        db.add(
            EmployeeAvailability(
                organization_id=employee.organization_id,
                employee_id=employee.id,
                day_of_week=day,
                start_time=dt_time.fromisoformat(start),
                end_time=dt_time.fromisoformat(end),
            )
        )
    db.commit()


def set_override(
    db: Session,
    employee: Employee,
    *,
    date: dt_date,
    available: bool,
    start: str | None = None,
    end: str | None = None,
    reason: str | None = None,
) -> AvailabilityOverride:
    override = AvailabilityOverride(
        organization_id=employee.organization_id,
        employee_id=employee.id,
        date=date,
        available=available,
        start_time=dt_time.fromisoformat(start) if start else None,
        end_time=dt_time.fromisoformat(end) if end else None,
        reason=reason,
    )
    db.add(override)
    db.commit()
    return override


def make_vehicle(
    db: Session,
    organization: Organization,
    customer: Customer,
    *,
    year: int = 2022,
    make: str = "BMW",
    model: str = "M3",
    license_plate: str | None = None,
) -> Vehicle:
    vehicle = Vehicle(
        organization_id=organization.id,
        customer_id=customer.id,
        year=year,
        make=make,
        model=model,
        color="Alpine White",
        license_plate=license_plate,
    )
    db.add(vehicle)
    db.commit()
    return vehicle


# ---------------------------------------------------------------- phase 3 factories


def future_start(days: int = 3, hour: int = 10) -> datetime:
    """A deterministic aware datetime safely in the future."""
    base = datetime.now(UTC) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


def make_booking(
    db: Session,
    organization: Organization,
    customer: Customer,
    vehicle: Vehicle,
    service: Service,
    *,
    start: datetime | None = None,
    status: BookingStatus = BookingStatus.PENDING,
    customer_notes: str | None = None,
) -> Booking:
    start = start or future_start()
    booking = Booking(
        organization_id=organization.id,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        service_id=service.id,
        requested_start=start,
        requested_end=start + timedelta(minutes=service.duration_minutes),
        status=status,
        customer_notes=customer_notes,
    )
    db.add(booking)
    db.commit()
    return booking


def make_job(
    db: Session,
    organization: Organization,
    booking: Booking,
    employee: Employee,
    *,
    status: JobStatus = JobStatus.ASSIGNED,
) -> Job:
    job = Job(
        organization_id=organization.id,
        booking_id=booking.id,
        employee_id=employee.id,
        scheduled_start=booking.requested_start,
        scheduled_end=booking.requested_end,
        status=status,
    )
    db.add(job)
    db.commit()
    return job


def booking_setup(db: Session, organization: Organization) -> dict:
    """A customer with a vehicle, a service, and an employee qualified for it.

    Emails are suffixed because users are globally unique: a test that builds two
    organizations calls this twice.
    """
    tag = uuid.uuid4().hex[:8]
    # The service name is unique per organization, so it is tagged too - a test
    # that builds two jobs in one org calls this twice.
    service = make_service(db, organization, name=f"Full Detail {tag}", duration_minutes=150)
    customer = make_customer(
        db, organization, email=f"booker-{tag}@example.com", first_name="Booker"
    )
    vehicle = make_vehicle(db, organization, customer)
    employee = make_employee(db, organization, email=f"tech-{tag}@example.com", services=[service])
    user = db.get(User, customer.user_id)
    assert user is not None
    employee_user = db.get(User, employee.user_id)
    assert employee_user is not None
    return {
        "service": service,
        "customer": customer,
        "customer_user": user,
        "vehicle": vehicle,
        "employee": employee,
        "employee_user": employee_user,
    }


# ---------------------------------------------------------------- phase 5 helpers

# The smallest real files of each type, so upload tests move actual bytes with
# correct magic numbers rather than arbitrary padding.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)
WEBP_1PX = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")


def make_job_note(
    db: Session,
    organization: Organization,
    job: Job,
    author: User,
    *,
    content: str = "A note",
    visibility: NoteVisibility = NoteVisibility.INTERNAL,
) -> JobNote:
    note = JobNote(
        organization_id=organization.id,
        job_id=job.id,
        author_id=author.id,
        content=content,
        visibility=visibility,
    )
    db.add(note)
    db.commit()
    return note


def job_with_parties(db: Session, organization: Organization) -> dict:
    """A confirmed job plus every principal who has a stake in it."""
    setup = booking_setup(db, organization)
    booking = make_booking(
        db,
        organization,
        setup["customer"],
        setup["vehicle"],
        setup["service"],
        status=BookingStatus.CONFIRMED,
    )
    job = make_job(db, organization, booking, setup["employee"])
    return {**setup, "booking": booking, "job": job}


# ---------------------------------------------------------------- phase 6 helpers

MAILPIT_API = "http://127.0.0.1:8025/api/v1"


def mailpit_clear() -> None:
    """Empty the capture mailbox so a test can assert on exactly what it sent."""
    httpx.delete(f"{MAILPIT_API}/messages", timeout=5)


def mailpit_messages() -> list[dict]:
    response = httpx.get(f"{MAILPIT_API}/messages?limit=50", timeout=5)
    response.raise_for_status()
    return list(response.json()["messages"])


def mailpit_body(message_id: str) -> str:
    response = httpx.get(f"{MAILPIT_API}/message/{message_id}", timeout=5)
    response.raise_for_status()
    payload = response.json()
    return f"{payload.get('Text', '')}\n{payload.get('HTML', '')}"


@pytest.fixture()
def mailbox() -> Iterator[None]:
    """A clean MailPit mailbox around each email test."""
    mailpit_clear()
    yield
    mailpit_clear()


class RecordingProvider:
    """A provider that records instead of sending, for failure-path tests."""

    name = "recording"

    def __init__(self, *, fail_times: int = 0, permanent: bool = False) -> None:
        self.sent: list[object] = []
        self.attempts = 0
        self._fail_times = fail_times
        self._permanent = permanent

    def send(self, message: object) -> str:
        from serviceflow.services.email import EmailDeliveryError

        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise EmailDeliveryError("provider unavailable", permanent=self._permanent)
        self.sent.append(message)
        return f"recorded-{self.attempts}"


def email_rows(db: Session, **filters) -> list[Notification]:  # type: ignore[no-untyped-def]
    from serviceflow.db.models.enums import NotificationChannel

    return (
        db.query(Notification)
        .filter_by(channel=NotificationChannel.EMAIL, **filters)
        .order_by(Notification.created_at)
        .all()
    )


@pytest.fixture()
def rate_limiting() -> Iterator[None]:
    """Turn the limiter on for one test, against a clean set of Redis keys."""
    import redis as redis_module

    from serviceflow.core.config import get_settings
    from serviceflow.services import ratelimit

    settings = get_settings()
    previous = settings.rate_limiting_enabled
    object.__setattr__(settings, "rate_limiting_enabled", True)
    ratelimit.reset_client()

    client = redis_module.Redis.from_url(str(settings.redis_url))
    for key in client.scan_iter("sf:rl:*"):
        client.delete(key)

    yield

    for key in client.scan_iter("sf:rl:*"):
        client.delete(key)
    client.close()
    object.__setattr__(settings, "rate_limiting_enabled", previous)
    ratelimit.reset_client()
