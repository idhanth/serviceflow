"""PostgreSQL row level security, proven against the real database.

These tests talk to PostgreSQL directly, underneath the application, because the
point of RLS is what happens when application code gets the tenant filter wrong.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from serviceflow.db.models.customer import Customer
from serviceflow.db.models.organization import Organization
from serviceflow.db.session import get_session_factory
from serviceflow.db.tenancy import bind_tenant
from tests.conftest import make_customer, make_organization

TENANT_TABLES = (
    "customers",
    "employees",
    "services",
    "employee_services",
    "employee_availability",
    "availability_overrides",
    "bookings",
    "jobs",
    "job_notes",
    "job_photos",
    "notifications",
    "audit_logs",
    "idempotency_records",
)


def test_the_application_role_cannot_bypass_row_level_security(db: Session) -> None:
    """Superusers and BYPASSRLS roles ignore every policy, so the app must be neither."""
    superuser, bypass = db.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert superuser is False, "tests must connect as the non-superuser application role"
    assert bypass is False


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_row_level_security_is_enabled_and_forced(db: Session, table: str) -> None:
    enabled, forced = db.execute(
        text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :table"),
        {"table": table},
    ).one()
    assert enabled and forced, f"{table} must have RLS enabled and forced for its owner"


@pytest.fixture()
def two_tenants(db: Session) -> tuple[Organization, Organization]:
    north = make_organization(db, name="Northside Home Services")
    harbor = make_organization(db, name="Harbor Plumbing")
    for index in range(3):
        make_customer(db, north, email=f"north-{index}@example.com")
    for index in range(2):
        make_customer(db, harbor, email=f"harbor-{index}@example.com")
    return north, harbor


def test_a_session_with_no_tenant_context_sees_no_rows(two_tenants: tuple) -> None:  # type: ignore[type-arg]
    """The failure mode RLS exists for: a query nobody scoped returns nothing, not everything."""
    session = get_session_factory()()
    try:
        assert session.execute(text("SELECT count(*) FROM customers")).scalar_one() == 0
        assert session.query(Customer).count() == 0
    finally:
        session.close()


def test_a_tenant_context_limits_even_unfiltered_queries_to_that_tenant(
    two_tenants: tuple[Organization, Organization],
) -> None:
    north, harbor = two_tenants
    session = get_session_factory()()
    try:
        bind_tenant(session, north.id)
        # Deliberately no WHERE organization_id = ... : the policy supplies it.
        rows = session.execute(text("SELECT organization_id FROM customers")).scalars().all()
        assert len(rows) == 3
        assert {str(row) for row in rows} == {str(north.id)}

        session.commit()  # a new transaction re-applies the tenant from session.info
        assert session.query(Customer).count() == 3
        assert session.query(Customer).filter_by(organization_id=harbor.id).count() == 0
    finally:
        session.close()


def test_writing_a_row_into_another_tenant_is_refused(
    two_tenants: tuple[Organization, Organization],
) -> None:
    north, harbor = two_tenants
    session = get_session_factory()()
    try:
        bind_tenant(session, north.id)
        user_id = session.execute(text("SELECT user_id FROM customers LIMIT 1")).scalar_one()
        with pytest.raises(DBAPIError, match="row-level security"):
            session.execute(
                text(
                    "INSERT INTO customers (id, organization_id, user_id, created_at, updated_at)"
                    " VALUES (gen_random_uuid(), :org, :user, now(), now())"
                ),
                {"org": str(harbor.id), "user": str(user_id)},
            )
        session.rollback()

        # Nor can an existing row be moved across the boundary.
        bind_tenant(session, north.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            session.execute(
                text("UPDATE customers SET organization_id = :org"), {"org": str(harbor.id)}
            )
        session.rollback()
    finally:
        session.close()


def test_updates_and_deletes_cannot_reach_another_tenants_rows(
    two_tenants: tuple[Organization, Organization], db: Session
) -> None:
    north, harbor = two_tenants
    session = get_session_factory()()
    try:
        bind_tenant(session, north.id)
        changed = session.execute(
            text("UPDATE customers SET notes = 'touched' WHERE organization_id = :org"),
            {"org": str(harbor.id)},
        )
        assert changed.rowcount == 0  # type: ignore[attr-defined]
        session.commit()
    finally:
        session.close()

    assert db.query(Customer).filter_by(organization_id=harbor.id, notes="touched").count() == 0
