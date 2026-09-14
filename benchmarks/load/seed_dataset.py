"""Bulk-load a realistic multi-tenant dataset for load testing.

    uv run --project apps/api python benchmarks/load/seed_dataset.py \\
        --database-url postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433/serviceflow_load

Defaults: 25 tenants, 20 technicians and 400 customers each - 500 technicians,
10,000 customers - and 2,000 bookings per tenant, each with its job: 50,000 of
both. Rows are written with PostgreSQL COPY, so the whole dataset loads in
seconds, and they obey every constraint the application's own writes do: jobs
never overlap for a technician, every booking has exactly one job, and every
reference stays inside its tenant. The load test would otherwise be measuring a
database the product could never have produced.

The accounts the load test signs in as get the benchmark password; everyone
else has none and cannot sign in.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
import uuid
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps/api/src"))

LOAD_PASSWORD = "load-password-2026"
SERVICES = [
    ("HVAC Inspection", 60, "129.00"),
    ("Preventive Maintenance", 90, "149.00"),
    ("Emergency Plumbing Repair", 120, "289.00"),
    ("Drain Cleaning", 60, "179.00"),
    ("Electrical Safety Inspection", 90, "199.00"),
    ("Water Heater Installation", 240, "1450.00"),
    ("Consultation", 30, "0.00"),
    ("Duct Cleaning", 120, "349.00"),
]
FIRST = ["Sarah", "James", "Emily", "Michael", "Olivia", "Daniel", "Rachel", "Brian", "Grace", "Marcus",
         "Priya", "Chris", "Jordan", "Maya", "Sam", "Nina", "Alex", "Dana", "Kevin", "Lena"]  # fmt: skip
LAST = ["Mitchell", "Carter", "Rodriguez", "Thompson", "Bennett", "Nguyen", "Kim", "O'Connor", "Patel",
        "Lee", "Morgan", "Brooks", "Rivera", "Shah", "Hale", "Tran", "Park", "Walsh", "Souza", "Delgado"]  # fmt: skip
STREETS = [
    "Maple Ave",
    "Oak Street",
    "Ridge Road",
    "Central Street",
    "Lake Street",
    "Park Place",
    "Grove Street",
]


# PostgreSQL refuses COPY into a table with row level security, so those tables
# are loaded through an unprotected temporary staging table and an INSERT, which
# RLS does check (and which passes here because setup runs with the bypass on).
RLS_TABLES = {
    "customers", "employees", "services", "employee_services", "employee_availability",
    "bookings", "jobs",
}  # fmt: skip


def copy(cursor: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple]) -> None:  # type: ignore[type-arg]
    target = f"staging_{table}" if table in RLS_TABLES else table
    if target != table:
        cursor.execute(f"CREATE TEMP TABLE IF NOT EXISTS {target} (LIKE {table} INCLUDING DEFAULTS)")
        cursor.execute(f"TRUNCATE {target}")
    with cursor.copy(f"COPY {target} ({', '.join(columns)}) FROM STDIN") as copier:
        for row in rows:
            copier.write_row(row)
    if target != table:
        listed = ", ".join(columns)
        cursor.execute(f"INSERT INTO {table} ({listed}) SELECT {listed} FROM {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tenants", type=int, default=25)
    parser.add_argument("--technicians", type=int, default=20, help="per tenant")
    parser.add_argument("--customers", type=int, default=400, help="per tenant")
    parser.add_argument("--bookings", type=int, default=2000, help="per tenant")
    parser.add_argument("--manifest", default=str(REPO / "benchmarks/load/.dataset.json"))
    parser.add_argument("--seed", type=int, default=20260914)
    args = parser.parse_args()

    from serviceflow.auth.passwords import hash_password

    random.seed(args.seed)
    started = time.perf_counter()
    password = hash_password(LOAD_PASSWORD)
    now = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    today = now.replace(hour=0)
    dsn = args.database_url.replace("postgresql+psycopg://", "postgresql://")
    manifest: dict[str, object] = {"password": LOAD_PASSWORD, "tenants": []}
    totals = {
        "tenants": 0,
        "users": 0,
        "technicians": 0,
        "customers": 0,
        "services": 0,
        "bookings": 0,
        "jobs": 0,
    }

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_config('app.rls_bypass', 'on', false)")
        if cur.execute("SELECT count(*) FROM organizations").fetchone()[0]:  # type: ignore[index]
            sys.exit("database already has tenants; build a fresh one (scripts/load-test.sh reset)")

        for t in range(args.tenants):
            org = uuid.uuid4()
            slug = f"load-tenant-{t:02d}"
            cur.execute(
                "INSERT INTO organizations (id, name, slug, email, timezone, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, 'UTC', now(), now())",
                (org, f"Load Tenant {t:02d}", slug, f"{slug}@load.example.com"),
            )
            users: list[tuple] = []  # type: ignore[type-arg]
            memberships: list[tuple] = []  # type: ignore[type-arg]

            def user(email: str, first: str, last: str, *, signs_in: bool) -> uuid.UUID:
                identifier = uuid.uuid4()
                users.append((identifier, f"dev|{email}", email, first, last, password if signs_in else None))  # noqa: B023
                return identifier

            accounts = {}
            for role in ("owner", "dispatcher", "analyst"):
                email = f"{role}@{slug}.load.example.com"
                identifier = user(email, role.title(), "Load", signs_in=True)
                memberships.append((uuid.uuid4(), org, identifier, role.upper(), "ACTIVE"))
                accounts[role] = email

            services = [(uuid.uuid4(), org, name, minutes, price, True) for name, minutes, price in SERVICES]
            technicians: list[uuid.UUID] = []
            employee_rows, qualification_rows, availability_rows = [], [], []
            for e in range(args.technicians):
                email = f"tech{e:02d}@{slug}.load.example.com"
                identifier = user(email, random.choice(FIRST), random.choice(LAST), signs_in=e == 0)
                memberships.append((uuid.uuid4(), org, identifier, "TECHNICIAN", "ACTIVE"))
                employee = uuid.uuid4()
                technicians.append(employee)
                employee_rows.append((employee, org, identifier, "Field Technician", True))
                for service in services:
                    qualification_rows.append((org, employee, service[0]))
                for day in range(7):
                    availability_rows.append((uuid.uuid4(), org, employee, day, dt.time(6, 0), dt.time(20, 0)))
                if e == 0:
                    accounts["technician"] = email

            customers: list[uuid.UUID] = []
            customer_rows = []
            for c in range(args.customers):
                email = f"customer{c:04d}@{slug}.load.example.com"
                first, last = random.choice(FIRST), random.choice(LAST)
                identifier = user(email, first, last, signs_in=c == 0)
                memberships.append((uuid.uuid4(), org, identifier, "CUSTOMER", "ACTIVE"))
                customer = uuid.uuid4()
                customers.append(customer)
                customer_rows.append(
                    (
                        customer,
                        org,
                        identifier,
                        f"{random.randint(100, 4999)} {random.choice(STREETS)}",
                    )
                )
                if c == 0:
                    accounts["customer"] = email

            # Bookings: each technician's work laid end to end in three daily slots,
            # spanning from about two months ago to two months ahead. Sequential
            # placement is what guarantees no overlaps without asking the database.
            booking_rows, job_rows = [], []
            per_technician = args.bookings // args.technicians
            for e, employee in enumerate(technicians):
                for n in range(per_technician):
                    day = -60 + (n // 3) * 2 + e % 2
                    hour = (8, 11, 14)[n % 3]
                    service = services[(n + e) % len(services)]
                    minutes = min(service[3], 150)
                    start = today + dt.timedelta(days=day, hours=hour)
                    end = start + dt.timedelta(minutes=service[3] if service[3] <= 150 else 150)
                    if service[3] > 150:  # keep long services inside the slot
                        service = services[0]
                        end = start + dt.timedelta(minutes=service[3])
                    _ = minutes
                    customer = customers[(e * 37 + n) % len(customers)]
                    booking, job = uuid.uuid4(), uuid.uuid4()
                    roll = random.random()
                    if end < now:
                        booking_status, job_status, assigned = (
                            ("CANCELLED", "CANCELLED", None) if roll < 0.06 else ("CONFIRMED", "COMPLETED", employee)
                        )
                    elif roll < 0.12:
                        booking_status, job_status, assigned = "PENDING", "NEW", None
                    elif roll < 0.16:
                        booking_status, job_status, assigned = "CANCELLED", "CANCELLED", None
                    else:
                        booking_status, job_status, assigned = "CONFIRMED", "SCHEDULED", employee
                    created = start - dt.timedelta(days=random.randint(2, 20))
                    booking_rows.append(
                        (
                            booking,
                            org,
                            customer,
                            service[0],
                            start,
                            end,
                            booking_status,
                            created,
                            created,
                        )
                    )
                    job_rows.append(
                        (
                            job, org, booking, assigned, start, end, job_status,
                            start if job_status == "COMPLETED" else None,
                            end if job_status == "COMPLETED" else None,
                            created, created,
                        )
                    )  # fmt: skip

            copy(
                cur,
                "users",
                ["id", "auth_provider_id", "email", "first_name", "last_name", "password_hash"],
                users,
            )
            copy(
                cur,
                "organization_memberships",
                ["id", "organization_id", "user_id", "role", "status"],
                memberships,
            )
            copy(
                cur,
                "services",
                ["id", "organization_id", "name", "duration_minutes", "base_price", "active"],
                services,
            )
            copy(
                cur,
                "employees",
                ["id", "organization_id", "user_id", "job_title", "active"],
                employee_rows,
            )
            copy(
                cur,
                "employee_services",
                ["organization_id", "employee_id", "service_id"],
                qualification_rows,
            )
            copy(
                cur,
                "employee_availability",
                ["id", "organization_id", "employee_id", "day_of_week", "start_time", "end_time"],
                availability_rows,
            )
            copy(cur, "customers", ["id", "organization_id", "user_id", "address"], customer_rows)
            copy(
                cur,
                "bookings",
                [
                    "id",
                    "organization_id",
                    "customer_id",
                    "service_id",
                    "requested_start",
                    "requested_end",
                    "status",
                    "created_at",
                    "updated_at",
                ],
                booking_rows,
            )
            copy(cur, "jobs", ["id", "organization_id", "booking_id", "employee_id", "scheduled_start", "scheduled_end", "status", "started_at", "completed_at", "created_at", "updated_at"], job_rows)  # fmt: skip

            manifest["tenants"].append({"slug": slug, "id": str(org), "accounts": accounts})  # type: ignore[attr-defined]
            totals["tenants"] += 1
            totals["users"] += len(users)
            totals["technicians"] += len(employee_rows)
            totals["customers"] += len(customer_rows)
            totals["services"] += len(services)
            totals["bookings"] += len(booking_rows)
            totals["jobs"] += len(job_rows)
        conn.commit()
        cur.execute("ANALYZE")

    manifest["totals"] = totals
    Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({**totals, "seconds": round(time.perf_counter() - started, 1)}))


if __name__ == "__main__":
    main()
