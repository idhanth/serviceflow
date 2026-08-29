"""Test fixtures. Every test runs against a dedicated database, never the dev one."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

# Settings are cached at import time, so the test environment must be set first.
_DEV_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://localhost:5433/serviceflow")
TEST_DATABASE_URL = _DEV_URL.rsplit("/", 1)[0] + "/serviceflow_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-definitely-long-enough-123")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/1")

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from serviceflow.auth.passwords import hash_password  # noqa: E402
from serviceflow.db.models import Base  # noqa: E402
from serviceflow.db.models.enums import MembershipStatus, Role  # noqa: E402
from serviceflow.db.models.membership import OrganizationMembership  # noqa: E402
from serviceflow.db.models.organization import Organization  # noqa: E402
from serviceflow.db.models.user import User  # noqa: E402
from serviceflow.db.session import get_engine, get_session_factory, reset_engine  # noqa: E402
from serviceflow.main import create_app  # noqa: E402

TEST_PASSWORD = "test-password-123"


def _admin_dsn() -> str:
    return (
        TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0]
        + "/postgres"
    )


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')
    reset_engine()
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    yield
    reset_engine()


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
    yield
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
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
) -> User:
    email = email or f"{role.value.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        auth_provider_id=f"dev|{email}",
        email=email,
        first_name=role.value.title(),
        last_name="Tester",
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
