"""seven roles, tenant integrity and row level security

Revision ID: e8cbe3405d1d
Revises: 459cd1aaa6af
Create Date: 2026-09-14 11:02:41.118420

What this revision changes, in order:

1. Roles. The three-role model (ADMIN, EMPLOYEE, CUSTOMER) becomes six tenant
   roles - OWNER, MANAGER, DISPATCHER, TECHNICIAN, CUSTOMER, ANALYST - plus the
   platform administrator, which is a flag on the user because it is not held
   inside any tenant. Existing ADMINs become OWNERs, EMPLOYEEs TECHNICIANs.
2. Jobs. Every booking now has a job from the moment it is created, so a job can
   be NEW (unassigned) before it is SCHEDULED. ASSIGNED becomes SCHEDULED and
   bookings that had no job get one.
3. Field service. The auto-detailing `vehicles` table goes; the work happens at
   the customer's address instead.
4. Tenant integrity in the database. Every reference between tenant-owned rows
   becomes a composite foreign key on (organization_id, id), so a row that
   pairs one tenant's record with another tenant's is refused by PostgreSQL.
5. Booking safety. The overlap exclusion constraint becomes tenant-aware and a
   partial unique index refuses an exact duplicate open booking.
6. Row level security, enabled and forced, on every tenant-owned table.

Irreversible: vehicle rows are dropped, so there is no faithful downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8cbe3405d1d"
down_revision: str | Sequence[str] | None = "459cd1aaa6af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table whose rows belong to one tenant. organization_memberships is
# deliberately absent: it is how a request *finds* its tenant, so it is read
# before any tenant context exists, always filtered by the verified user id.
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

TENANT_PREDICATE = (
    "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
    " OR current_setting('app.rls_bypass', true) = 'on'"
)


def _replace_enum(type_name: str, values: Sequence[str], column_sql: dict[str, str]) -> None:
    """Swap an enum for a new value set, mapping existing rows with the given SQL.

    A fresh type rather than ALTER TYPE ... ADD VALUE: PostgreSQL refuses to use
    a value added that way until the transaction commits, and the constraints
    later in this migration need the new values immediately.
    """
    quoted = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE {type_name}_v2 AS ENUM ({quoted})")
    for table_column, mapping in column_sql.items():
        table, column = table_column.split(".")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name}_v2 "
            f"USING ({mapping})::{type_name}_v2"
        )
    op.execute(f"DROP TYPE {type_name}")
    op.execute(f"ALTER TYPE {type_name}_v2 RENAME TO {type_name}")


def upgrade() -> None:
    """Upgrade schema."""
    # ---- 1. roles -------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    _replace_enum(
        "role",
        ("OWNER", "MANAGER", "DISPATCHER", "TECHNICIAN", "CUSTOMER", "ANALYST"),
        {
            "organization_memberships.role": (
                "CASE role::text WHEN 'ADMIN' THEN 'OWNER'"
                " WHEN 'EMPLOYEE' THEN 'TECHNICIAN' ELSE role::text END"
            )
        },
    )

    # ---- 2. jobs --------------------------------------------------------------
    # The old constraint names the old enum type, so it has to go first.
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_no_overlapping_assignments")
    _replace_enum(
        "job_status",
        ("NEW", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"),
        {"jobs.status": "CASE status::text WHEN 'ASSIGNED' THEN 'SCHEDULED' ELSE status::text END"},
    )
    op.alter_column("jobs", "employee_id", existing_type=sa.UUID(), nullable=True)
    op.execute(
        """
        INSERT INTO jobs (id, organization_id, booking_id, employee_id,
                          scheduled_start, scheduled_end, status, created_at, updated_at)
        SELECT gen_random_uuid(), b.organization_id, b.id, NULL,
               b.requested_start, b.requested_end,
               CASE WHEN b.status = 'PENDING' THEN 'NEW' ELSE 'CANCELLED' END::job_status,
               b.created_at, now()
        FROM bookings b
        WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.booking_id = b.id)
        """
    )
    op.create_check_constraint(
        op.f("ck_jobs_active_jobs_assigned"),
        "jobs",
        "status IN ('NEW', 'CANCELLED') OR employee_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_jobs_new_jobs_unassigned"), "jobs", "status <> 'NEW' OR employee_id IS NULL"
    )

    # ---- audit actions: vehicles are gone, members and tenants arrive ----------
    op.execute("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_no_update_or_delete")
    op.execute("DELETE FROM audit_logs WHERE action = 'VEHICLE_ARCHIVED'")
    op.execute("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_no_update_or_delete")
    _replace_enum(
        "audit_action",
        (
            "BOOKING_CREATED",
            "BOOKING_CONFIRMED",
            "BOOKING_REJECTED",
            "BOOKING_RESCHEDULED",
            "BOOKING_CANCELLED",
            "JOB_ASSIGNED",
            "JOB_REASSIGNED",
            "JOB_STARTED",
            "JOB_COMPLETED",
            "JOB_CANCELLED",
            "NOTE_ADDED",
            "NOTE_DELETED",
            "PHOTO_DELETED",
            "CUSTOMER_CREATED",
            "CUSTOMER_UPDATED",
            "CUSTOMER_ARCHIVED",
            "EMPLOYEE_CREATED",
            "EMPLOYEE_UPDATED",
            "EMPLOYEE_DEACTIVATED",
            "EMPLOYEE_REACTIVATED",
            "SERVICE_CREATED",
            "SERVICE_UPDATED",
            "SERVICE_RETIRED",
            "USER_INVITED",
            "USER_ROLE_CHANGED",
            "MEMBER_SUSPENDED",
            "MEMBER_REACTIVATED",
            "ORGANIZATION_UPDATED",
            "TENANT_CREATED",
            "AVAILABILITY_UPDATED",
            "AVAILABILITY_OVERRIDE_SET",
            "AVAILABILITY_OVERRIDE_REMOVED",
        ),
        {"audit_logs.action": "action::text"},
    )

    # ---- 3. field service: no vehicles ---------------------------------------
    op.drop_constraint(op.f("fk_bookings_vehicle_id_vehicles"), "bookings", type_="foreignkey")
    op.drop_index(op.f("ix_bookings_vehicle_id"), table_name="bookings")
    op.drop_column("bookings", "vehicle_id")
    op.drop_table("vehicles")
    op.add_column("customers", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    # ---- 4. composite tenant foreign keys ------------------------------------
    for table in ("customers", "employees", "services", "bookings", "jobs"):
        op.create_unique_constraint(
            op.f(f"uq_{table}_organization_id_id"), table, ["organization_id", "id"]
        )

    def retarget(table: str, column: str, parent: str, ondelete: str) -> None:
        op.drop_constraint(op.f(f"fk_{table}_{column}_{parent}"), table, type_="foreignkey")
        op.create_foreign_key(
            op.f(f"fk_{table}_organization_id_{parent}"),
            table,
            parent,
            ["organization_id", column],
            ["organization_id", "id"],
            ondelete=ondelete,
        )

    retarget("bookings", "customer_id", "customers", "RESTRICT")
    retarget("bookings", "service_id", "services", "RESTRICT")
    retarget("jobs", "booking_id", "bookings", "CASCADE")
    retarget("jobs", "employee_id", "employees", "RESTRICT")
    retarget("employee_availability", "employee_id", "employees", "CASCADE")
    retarget("availability_overrides", "employee_id", "employees", "CASCADE")
    retarget("job_notes", "job_id", "jobs", "CASCADE")
    retarget("job_photos", "job_id", "jobs", "CASCADE")

    op.add_column("employee_services", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE employee_services es SET organization_id = e.organization_id"
        " FROM employees e WHERE e.id = es.employee_id"
    )
    op.alter_column("employee_services", "organization_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_employee_services_organization_id_organizations"),
        "employee_services",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    retarget("employee_services", "employee_id", "employees", "CASCADE")
    retarget("employee_services", "service_id", "services", "CASCADE")
    op.create_index("ix_employee_services_service_id", "employee_services", ["service_id"])

    # ---- 5. booking safety ----------------------------------------------------
    # A retried or double-clicked submission cannot store the same open booking
    # twice, whatever path it takes to the table.
    op.create_index(
        "uq_bookings_no_duplicate_open",
        "bookings",
        ["organization_id", "customer_id", "service_id", "requested_start"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'CONFIRMED')"),
    )
    # No technician can hold two live jobs whose time ranges overlap. The range
    # is half-open, so 10:00-12:00 and 12:00-14:00 do not conflict. Completed work
    # still blocks: that time was really spent. Like the original constraint,
    # this fails on existing overlapping rows rather than deleting any.
    op.execute(
        """
        ALTER TABLE jobs
        ADD CONSTRAINT jobs_no_overlapping_assignments
        EXCLUDE USING gist (
            organization_id WITH =,
            employee_id WITH =,
            tstzrange(scheduled_start, scheduled_end) WITH &&
        ) WHERE (employee_id IS NOT NULL AND status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED'))
        """
    )

    # ---- 6. row level security -----------------------------------------------
    # FORCE applies the policy to the table owner too, which is the role the
    # application connects as. Superusers bypass RLS regardless, which is why the
    # application must never connect as one (tests/test_row_level_security.py
    # fails if it does).
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table}"
            f" USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "e8cbe3405d1d drops vehicle data and remaps roles; restore from a backup instead."
    )
