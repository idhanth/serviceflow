"""Tenant isolation and booking-safety benchmark.

Attempts thousands of writes that must never succeed, against a running API and
the PostgreSQL database behind it, and records what happened to every one.

    uv run --project apps/api python benchmarks/tenant_isolation/run.py \\
        --base-url http://127.0.0.1:8200 \\
        --database-url postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433/serviceflow_bench \\
        --output benchmarks/results/tenant_isolation.json

`scripts/bench-isolation.sh` builds a throwaway database and API and runs this.

What counts
-----------
Every attempt is an *invalid* write or read: a duplicate or overlapping booking,
a reference to another tenant's record, another tenant's resource by id, or an
action the caller's role does not grant. An attempt is

  * blocked               - refused with the expected 4xx, or by the database;
  * an unexpected success - the API returned 2xx, or the database committed it;
  * a server error        - 5xx. Not a success, but not a clean refusal either,
                            so it is reported separately and fails the run.

The number of attempts is whatever the configuration below generates. It is
not a target: change the tenant, technician or slot counts and it changes.

Legitimate control writes run alongside - the bookings the attacks collide with,
and the one winner of every concurrent race - so a system that refused
everything could not pass. After the run the database is checked directly for
the invariants the attacks were aiming at.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import random
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

REPO = Path(__file__).resolve().parents[2]
PASSWORD = "bench-password-2026"
EXPECTED_REFUSALS = {403, 404, 409, 422}

CATEGORIES = {
    "exact_duplicate_booking": "The same customer, service and start submitted again.",
    "overlapping_employee_booking": "A technician booked into time they already hold.",
    "concurrent_double_booking": "Simultaneous requests racing for one technician's slot (losers only).",
    "cross_tenant_customer": "A booking naming another tenant's customer.",
    "cross_tenant_employee": "A booking or assignment naming another tenant's technician.",
    "cross_tenant_service": "A booking naming another tenant's service.",
    "cross_tenant_resource_access": "Reading or changing another tenant's bookings, jobs or customers by id.",
    "unauthorized_role": "An action the caller's role does not grant.",
    "database_level_bypass": "Raw SQL writes that skip the application entirely.",
}


# --------------------------------------------------------------------------- setup


@dataclass
class Tenant:
    index: int
    id: str
    tokens: dict[str, str] = field(default_factory=dict)
    customer_ids: list[str] = field(default_factory=list)
    customer_user_tokens: list[str] = field(default_factory=list)
    service_ids: list[str] = field(default_factory=list)
    employee_ids: list[str] = field(default_factory=list)
    technician_employee_id: str = ""
    booking_ids: list[str] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    anchors: list[dict[str, Any]] = field(default_factory=list)


def build_tenants(database_url: str, *, tenants: int, technicians: int, customers: int) -> list[dict[str, Any]]:
    """Create the tenants directly in the database, with RLS bypassed for setup only."""
    sys.path.insert(0, str(REPO / "apps/api/src"))
    from serviceflow.auth.passwords import hash_password
    from serviceflow.db.models import (
        Customer,
        Employee,
        EmployeeAvailability,
        EmployeeService,
        MembershipStatus,
        Organization,
        OrganizationMembership,
        Role,
        Service,
        User,
    )

    engine = create_engine(database_url, future=True)
    factory = sessionmaker(bind=engine, future=True)
    password_hash = hash_password(PASSWORD)
    run = uuid.uuid4().hex[:6]
    created: list[dict[str, Any]] = []

    with factory() as db:
        db.execute(text("SELECT set_config('app.rls_bypass', 'on', false)"))

        def person(org: Organization, role: Role, label: str) -> User:
            email = f"{label}.{run}@bench.example.com"
            user = User(
                auth_provider_id=f"dev|{email}",
                email=email,
                first_name=label.split("-")[0].title(),
                last_name="Bench",
                password_hash=password_hash,
            )
            db.add(user)
            db.flush()
            db.add(
                OrganizationMembership(
                    organization_id=org.id,
                    user_id=user.id,
                    role=role,
                    status=MembershipStatus.ACTIVE,
                )
            )
            return user

        for t in range(tenants):
            org = Organization(
                name=f"Bench Tenant {t}",
                slug=f"bench-{run}-{t}",
                email=f"t{t}@bench.example.com",
                timezone="UTC",
            )
            db.add(org)
            db.flush()
            users = {
                role: person(org, getattr(Role, role.upper()), f"{role}-t{t}")
                for role in ("owner", "dispatcher", "analyst")
            }
            services = [
                Service(
                    organization_id=org.id,
                    name=f"Service {s}",
                    base_price=Decimal("120.00"),
                    duration_minutes=60,
                )
                for s in range(3)
            ]
            db.add_all(services)
            db.flush()
            employees: list[Employee] = []
            technician_user = None
            for e in range(technicians):
                user = person(org, Role.TECHNICIAN, f"tech{e}-t{t}")
                technician_user = technician_user or user
                employee = Employee(organization_id=org.id, user_id=user.id, job_title="Technician")
                db.add(employee)
                db.flush()
                for service in services:
                    db.add(EmployeeService(organization_id=org.id, employee_id=employee.id, service_id=service.id))
                for day in range(7):
                    db.add(
                        EmployeeAvailability(
                            organization_id=org.id,
                            employee_id=employee.id,
                            day_of_week=day,
                            start_time=dt.time(0, 0),
                            end_time=dt.time(23, 59),
                        )
                    )
                employees.append(employee)
            customer_rows: list[tuple[Customer, User]] = []
            for c in range(customers):
                user = person(org, Role.CUSTOMER, f"cust{c}-t{t}")
                customer = Customer(organization_id=org.id, user_id=user.id, address=f"{100 + c} Bench Street")
                db.add(customer)
                customer_rows.append((customer, user))
            db.flush()
            created.append(
                {
                    "id": str(org.id),
                    "emails": {role: user.email for role, user in users.items()}
                    | {"technician": technician_user.email},  # type: ignore[union-attr]
                    "service_ids": [str(s.id) for s in services],
                    "employee_ids": [str(e.id) for e in employees],
                    "customer_ids": [str(c.id) for c, _ in customer_rows],
                    "customer_emails": [u.email for _, u in customer_rows],
                    "technician_employee_id": str(employees[0].id),
                }
            )
        db.commit()
    engine.dispose()
    return created


# --------------------------------------------------------------------------- recording


@dataclass
class Ledger:
    attempts: Counter[str] = field(default_factory=Counter)
    blocked: Counter[str] = field(default_factory=Counter)
    unexpected: Counter[str] = field(default_factory=Counter)
    server_errors: Counter[str] = field(default_factory=Counter)
    refusal_codes: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    controls: Counter[str] = field(default_factory=Counter)
    control_failures: Counter[str] = field(default_factory=Counter)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def api(self, category: str, response: httpx.Response, label: str) -> None:
        with self.lock:
            self.attempts[category] += 1
            if response.status_code in EXPECTED_REFUSALS:
                self.blocked[category] += 1
                try:
                    code = response.json()["error"]["code"]
                except Exception:
                    code = f"HTTP_{response.status_code}"
                self.refusal_codes[category][code] += 1
            elif response.status_code >= 500:
                self.server_errors[category] += 1
                self._example(category, f"{label}: {response.status_code} {response.text[:160]}")
            else:
                self.unexpected[category] += 1
                self._example(category, f"{label}: {response.status_code} {response.text[:160]}")

    def database(self, category: str, refused: bool, label: str, detail: str) -> None:
        with self.lock:
            self.attempts[category] += 1
            if refused:
                self.blocked[category] += 1
                self.refusal_codes[category][detail] += 1
            else:
                self.unexpected[category] += 1
                self._example(category, f"{label}: committed")

    def control(self, name: str, ok: bool) -> None:
        with self.lock:
            (self.controls if ok else self.control_failures)[name] += 1

    def _example(self, category: str, line: str) -> None:
        if len(self.examples[category]) < 5:
            self.examples[category].append(line)


# --------------------------------------------------------------------------- the run


class Client:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=30.0, limits=httpx.Limits(max_connections=64))

    def login(self, email: str) -> str:
        response = self.http.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        response.raise_for_status()
        return str(response.json()["access_token"])

    def call(
        self,
        token: str,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self.http.request(
            method,
            f"/api/v1{path}",
            json=body,
            headers={"Authorization": f"Bearer {token}", **(headers or {})},
        )


def slot(day: int, hour: int, minute: int = 0) -> dt.datetime:
    base = dt.datetime.now(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=30 + day)
    return base.replace(hour=hour, minute=minute)


def run(args: argparse.Namespace) -> dict[str, Any]:
    random.seed(args.seed)
    started = time.perf_counter()
    specs = build_tenants(
        args.database_url,
        tenants=args.tenants,
        technicians=args.technicians,
        customers=args.customers,
    )
    client = Client(args.base_url)
    ledger = Ledger()
    pool = ThreadPoolExecutor(max_workers=args.concurrency)

    tenants: list[Tenant] = []
    for index, spec in enumerate(specs):
        tenant = Tenant(index=index, id=spec["id"])
        tenant.tokens = {role: client.login(email) for role, email in spec["emails"].items()}
        tenant.customer_ids = spec["customer_ids"]
        tenant.customer_user_tokens = [client.login(email) for email in spec["customer_emails"][:2]]
        tenant.service_ids = spec["service_ids"]
        tenant.employee_ids = spec["employee_ids"]
        tenant.technician_employee_id = spec["technician_employee_id"]
        tenants.append(tenant)

    # ---- controls: the legitimate bookings every attack is aimed at -------------
    def anchor(tenant: Tenant, employee_index: int, slot_index: int) -> None:
        start = slot(slot_index, 8 + employee_index % 8)
        body = {
            "customer_id": tenant.customer_ids[slot_index % len(tenant.customer_ids)],
            "service_id": tenant.service_ids[slot_index % len(tenant.service_ids)],
            "employee_id": tenant.employee_ids[employee_index],
            "requested_start": start.isoformat(),
        }
        response = client.call(tenant.tokens["dispatcher"], "POST", "/bookings", body)
        ok = response.status_code == 201
        ledger.control("anchor_booking_created", ok)
        if ok:
            data = response.json()["data"]
            tenant.anchors.append({**body, "start": start, "booking_id": data["id"], "job_id": data["job"]["id"]})
            tenant.booking_ids.append(data["id"])
            tenant.job_ids.append(data["job"]["id"])

    list(
        pool.map(
            lambda job: anchor(*job),
            [(t, e, s) for t in tenants for e in range(len(t.employee_ids)) for s in range(args.slots)],
        )
    )

    work: list[Callable[[], None]] = []

    def attempt(
        category: str,
        token: str,
        method: str,
        path: str,
        body: Any = None,
        label: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        work.append(
            lambda: ledger.api(
                category,
                client.call(token, method, path, body, headers),
                label or f"{method} {path}",
            )
        )

    for tenant in tenants:
        other = tenants[(tenant.index + 1) % len(tenants)]
        dispatcher = tenant.tokens["dispatcher"]

        for a in tenant.anchors:
            # 1. exact duplicates: the same booking again, with and without the technician,
            #    from staff, and from the owner as well.
            same = {k: a[k] for k in ("customer_id", "service_id", "requested_start")}
            attempt(
                "exact_duplicate_booking",
                dispatcher,
                "POST",
                "/bookings",
                same,
                "duplicate without technician",
            )
            attempt(
                "exact_duplicate_booking",
                dispatcher,
                "POST",
                "/bookings",
                {**same, "employee_id": a["employee_id"]},
                "duplicate with technician",
            )
            attempt(
                "exact_duplicate_booking",
                tenant.tokens["owner"],
                "POST",
                "/bookings",
                same,
                "duplicate by owner",
            )

            # 2. overlaps: every shape of collision with the technician's time, for a
            #    different customer so the duplicate rule is not what refuses it.
            other_customer = tenant.customer_ids[
                (tenant.customer_ids.index(a["customer_id"]) + 1) % len(tenant.customer_ids)
            ]
            for minutes in (0, 15, 30, 45, -30, -45):
                attempt(
                    "overlapping_employee_booking",
                    dispatcher,
                    "POST",
                    "/bookings",
                    {
                        "customer_id": other_customer,
                        "service_id": a["service_id"],
                        "employee_id": a["employee_id"],
                        "requested_start": (a["start"] + dt.timedelta(minutes=minutes)).isoformat(),
                    },
                    f"overlap {minutes:+} min",
                )

            # 3-5. cross-tenant references in an otherwise valid booking.
            foreign_customer = random.choice(other.customer_ids)
            foreign_service = random.choice(other.service_ids)
            foreign_employee = random.choice(other.employee_ids)
            free = (a["start"] + dt.timedelta(days=200)).isoformat()
            attempt(
                "cross_tenant_customer",
                dispatcher,
                "POST",
                "/bookings",
                {
                    "customer_id": foreign_customer,
                    "service_id": a["service_id"],
                    "requested_start": free,
                },
            )
            attempt(
                "cross_tenant_customer",
                tenant.tokens["owner"],
                "POST",
                "/bookings",
                {
                    "customer_id": foreign_customer,
                    "service_id": a["service_id"],
                    "employee_id": a["employee_id"],
                    "requested_start": free,
                },
            )
            attempt(
                "cross_tenant_service",
                dispatcher,
                "POST",
                "/bookings",
                {
                    "customer_id": a["customer_id"],
                    "service_id": foreign_service,
                    "requested_start": free,
                },
            )
            attempt(
                "cross_tenant_service",
                tenant.customer_user_tokens[0],
                "POST",
                "/bookings",
                {"service_id": foreign_service, "requested_start": free},
            )
            attempt(
                "cross_tenant_employee",
                dispatcher,
                "POST",
                "/bookings",
                {
                    "customer_id": a["customer_id"],
                    "service_id": a["service_id"],
                    "employee_id": foreign_employee,
                    "requested_start": free,
                },
            )
            attempt(
                "cross_tenant_employee",
                dispatcher,
                "POST",
                f"/jobs/{a['job_id']}/assign",
                {"employee_id": foreign_employee},
            )

        # 6. another tenant's resources, by id, every way in.
        for booking_id, job_id in zip(
            other.booking_ids[: args.access_sample],
            other.job_ids[: args.access_sample],
            strict=False,
        ):
            owner = tenant.tokens["owner"]
            attempt("cross_tenant_resource_access", owner, "GET", f"/bookings/{booking_id}")
            attempt(
                "cross_tenant_resource_access",
                owner,
                "PATCH",
                f"/bookings/{booking_id}",
                {"admin_notes": "cross-tenant"},
            )
            attempt("cross_tenant_resource_access", owner, "POST", f"/bookings/{booking_id}/cancel", {})
            attempt(
                "cross_tenant_resource_access",
                owner,
                "POST",
                f"/bookings/{booking_id}/reschedule",
                {"requested_start": slot(300, 9).isoformat()},
            )
            attempt("cross_tenant_resource_access", owner, "GET", f"/jobs/{job_id}")
            attempt(
                "cross_tenant_resource_access",
                owner,
                "PATCH",
                f"/jobs/{job_id}",
                {"status": "IN_PROGRESS"},
            )
            attempt("cross_tenant_resource_access", owner, "POST", f"/jobs/{job_id}/start")
            attempt(
                "cross_tenant_resource_access",
                owner,
                "POST",
                f"/jobs/{job_id}/notes",
                {"content": "x", "visibility": "INTERNAL"},
            )
            attempt(
                "cross_tenant_resource_access",
                tenant.tokens["technician"],
                "POST",
                f"/jobs/{job_id}/complete",
                {},
            )
        for customer_id in other.customer_ids:
            attempt(
                "cross_tenant_resource_access",
                tenant.tokens["owner"],
                "GET",
                f"/customers/{customer_id}",
            )
            attempt(
                "cross_tenant_resource_access",
                tenant.tokens["owner"],
                "PATCH",
                f"/customers/{customer_id}",
                {"notes": "cross-tenant"},
            )
            attempt(
                "cross_tenant_resource_access",
                tenant.tokens["owner"],
                "DELETE",
                f"/customers/{customer_id}",
            )
        # Naming the other tenant outright in the organization header.
        for path in ("/bookings", "/jobs", "/customers", "/dashboard"):
            attempt(
                "cross_tenant_resource_access",
                tenant.tokens["owner"],
                "GET",
                path,
                headers={"X-Organization-Id": other.id},
                label=f"header {path}",
            )

        # 7. roles acting beyond their permissions, inside their own tenant.
        sample = tenant.anchors[: args.access_sample]
        # The second signed-in customer must only ever aim at *other* customers'
        # bookings: cancelling their own would be a legitimate write, and it would
        # free the very slots the duplicate and overlap attacks rely on.
        second_customer = tenant.customer_ids[1]
        for a in sample:
            free = (a["start"] + dt.timedelta(days=120)).isoformat()
            new_booking = {
                "customer_id": a["customer_id"],
                "service_id": a["service_id"],
                "requested_start": free,
            }
            attempt(
                "unauthorized_role",
                tenant.tokens["technician"],
                "POST",
                "/bookings",
                new_booking,
                "technician books",
            )
            attempt(
                "unauthorized_role",
                tenant.tokens["analyst"],
                "POST",
                "/bookings",
                new_booking,
                "analyst books",
            )
            attempt(
                "unauthorized_role",
                tenant.customer_user_tokens[0],
                "POST",
                "/bookings",
                {**new_booking, "customer_id": tenant.customer_ids[-1]},
                "customer books for someone else",
            )
            attempt(
                "unauthorized_role",
                tenant.customer_user_tokens[0],
                "POST",
                f"/jobs/{a['job_id']}/assign",
                {"employee_id": a["employee_id"]},
                "customer assigns",
            )
            attempt(
                "unauthorized_role",
                tenant.tokens["analyst"],
                "POST",
                f"/jobs/{a['job_id']}/cancel",
                None,
                "analyst cancels job",
            )
            attempt(
                "unauthorized_role",
                tenant.tokens["analyst"],
                "PATCH",
                f"/jobs/{a['job_id']}",
                {"internal_notes": "x"},
                "analyst edits job",
            )
            if a["employee_id"] != tenant.technician_employee_id:
                attempt(
                    "unauthorized_role",
                    tenant.tokens["technician"],
                    "POST",
                    f"/jobs/{a['job_id']}/start",
                    None,
                    "technician starts a colleague's job",
                )
            if a["customer_id"] != second_customer:
                attempt(
                    "unauthorized_role",
                    tenant.customer_user_tokens[1],
                    "POST",
                    f"/bookings/{a['booking_id']}/cancel",
                    {},
                    "customer cancels someone else's booking",
                )
        for token_name in ("technician", "analyst", "dispatcher"):
            attempt(
                "unauthorized_role",
                tenant.tokens[token_name],
                "PATCH",
                "/organizations/current",
                {"name": "Renamed"},
                f"{token_name} edits settings",
            )
            attempt(
                "unauthorized_role",
                tenant.tokens[token_name],
                "POST",
                "/members",
                {
                    "email": f"x-{uuid.uuid4().hex[:6]}@bench.example.com",
                    "first_name": "X",
                    "last_name": "Y",
                    "role": "OWNER",
                },
                f"{token_name} grants owner",
            )
        attempt(
            "unauthorized_role",
            tenant.tokens["analyst"],
            "POST",
            "/customers",
            {
                "email": f"a-{uuid.uuid4().hex[:6]}@bench.example.com",
                "first_name": "A",
                "last_name": "B",
            },
            "analyst adds customer",
        )
        attempt(
            "unauthorized_role",
            tenant.tokens["technician"],
            "GET",
            "/customers",
            None,
            "technician lists customers",
        )
        attempt(
            "unauthorized_role",
            tenant.tokens["owner"],
            "GET",
            "/platform/tenants",
            None,
            "owner uses platform admin",
        )

    random.shuffle(work)
    list(pool.map(lambda task: task(), work))

    # 8. concurrent races: N requests for one technician's free slot at once.
    def race(tenant: Tenant, round_index: int) -> None:
        employee = tenant.employee_ids[round_index % len(tenant.employee_ids)]
        # Well inside the one-year booking window, and clear of every anchor.
        start = slot(250 + round_index, 10)
        barrier = threading.Barrier(args.race_size)

        def contender(position: int) -> httpx.Response:
            barrier.wait(timeout=30)
            return client.call(
                tenant.tokens["dispatcher"],
                "POST",
                "/bookings",
                {
                    "customer_id": tenant.customer_ids[position % len(tenant.customer_ids)],
                    "service_id": tenant.service_ids[position % len(tenant.service_ids)],
                    "employee_id": employee,
                    "requested_start": (start + dt.timedelta(minutes=position % 4 * 10)).isoformat(),
                },
            )

        with ThreadPoolExecutor(max_workers=args.race_size) as racers:
            responses = list(racers.map(contender, range(args.race_size)))
        winners = [r for r in responses if r.status_code == 201]
        ledger.control("race_winner", len(winners) == 1)
        # One winner is the legitimate booking; every other contender is an invalid write.
        losers = [r for r in responses if r is not (winners[0] if winners else None)]
        for response in losers:
            ledger.api("concurrent_double_booking", response, "race")

    for tenant in tenants:
        for round_index in range(args.race_rounds):
            race(tenant, round_index)

    # 9. underneath the API: raw SQL that skips every application check.
    database_attacks(args.database_url, tenants, ledger)

    invariants = check_invariants(args.database_url)
    duration = time.perf_counter() - started
    pool.shutdown()

    attempted = sum(ledger.attempts.values())
    blocked = sum(ledger.blocked.values())
    unexpected = sum(ledger.unexpected.values())
    server_errors = sum(ledger.server_errors.values())
    passed = (
        unexpected == 0
        and server_errors == 0
        and all(v == 0 for v in invariants.values())
        and not ledger.control_failures
    )

    return {
        "benchmark": "tenant_isolation",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "passed": passed,
        "summary": {
            "attempted": attempted,
            "blocked": blocked,
            "unexpected_successes": unexpected,
            "server_errors": server_errors,
            "block_rate": round(blocked / attempted, 6) if attempted else None,
        },
        "categories": {
            name: {
                "description": CATEGORIES[name],
                "attempted": ledger.attempts[name],
                "blocked": ledger.blocked[name],
                "unexpected_successes": ledger.unexpected[name],
                "server_errors": ledger.server_errors[name],
                "refusals": dict(ledger.refusal_codes[name]),
                "examples_of_failures": ledger.examples.get(name, []),
            }
            for name in CATEGORIES
        },
        "controls": {
            "succeeded": dict(ledger.controls),
            "failed": dict(ledger.control_failures),
            "note": "Legitimate writes that must succeed, so a system that refused everything could not pass.",
        },
        "database_invariants_violations": invariants,
        "configuration": {
            "tenants": args.tenants,
            "technicians_per_tenant": args.technicians,
            "customers_per_tenant": args.customers,
            "anchor_slots_per_technician": args.slots,
            "cross_tenant_access_sample": args.access_sample,
            "race_rounds_per_tenant": args.race_rounds,
            "race_size": args.race_size,
            "client_concurrency": args.concurrency,
            "seed": args.seed,
        },
        "environment": environment(args.database_url),
        "duration_seconds": round(duration, 1),
    }


def database_attacks(database_url: str, tenants: list[Tenant], ledger: Ledger) -> None:
    engine = create_engine(database_url, future=True)
    category = "database_level_bypass"

    def expect_refusal(label: str, sql: str, params: dict[str, Any], tenant_context: str | None = None) -> None:
        with Session(engine) as db:
            if tenant_context:
                db.execute(
                    text("SELECT set_config('app.organization_id', :org, true)"),
                    {"org": tenant_context},
                )
            else:
                db.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
            try:
                written = db.execute(text(sql), params).rowcount  # type: ignore[attr-defined]
                if written != 1:
                    # An attack that matched no row proves nothing either way.
                    raise RuntimeError(f"benchmark setup error: {label} matched {written} rows")
                db.commit()
                ledger.database(category, False, label, "")
            except DBAPIError as exc:
                db.rollback()
                constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                ledger.database(category, True, label, constraint or type(exc.orig).__name__)

    insert_booking = (
        "INSERT INTO bookings (id, organization_id, customer_id, service_id, requested_start, requested_end, status, created_at, updated_at)"
        " VALUES (gen_random_uuid(), :org, :customer, :service, :start, :end, 'PENDING', now(), now())"
    )
    for tenant in tenants:
        other = tenants[(tenant.index + 1) % len(tenants)]
        for a in tenant.anchors[:20]:
            start = a["start"] + dt.timedelta(days=500)
            window = {"start": start, "end": start + dt.timedelta(hours=1)}
            expect_refusal(
                "mixed-tenant customer",
                insert_booking,
                {
                    "org": tenant.id,
                    "customer": random.choice(other.customer_ids),
                    "service": a["service_id"],
                    **window,
                },
            )
            expect_refusal(
                "mixed-tenant service",
                insert_booking,
                {
                    "org": tenant.id,
                    "customer": a["customer_id"],
                    "service": random.choice(other.service_ids),
                    **window,
                },
            )
            expect_refusal(
                "duplicate open booking",
                insert_booking,
                {
                    "org": tenant.id,
                    "customer": a["customer_id"],
                    "service": a["service_id"],
                    "start": a["start"],
                    "end": a["start"] + dt.timedelta(hours=1),
                },
            )
            expect_refusal(
                "cross-tenant technician on a job",
                "UPDATE jobs SET employee_id = :employee WHERE id = :job",
                {"employee": random.choice(other.employee_ids), "job": a["job_id"]},
            )
            target = next(o for o in tenant.anchors if o["employee_id"] != a["employee_id"])
            expect_refusal(
                "overlapping job for one technician",
                "UPDATE jobs SET employee_id = :employee, scheduled_start = :start, scheduled_end = :end"
                " WHERE id = :target",
                {
                    "employee": a["employee_id"],
                    "target": target["job_id"],
                    "start": a["start"],
                    "end": a["start"] + dt.timedelta(minutes=30),
                },
            )
            expect_refusal(
                "row written into another tenant under RLS",
                insert_booking,
                {
                    "org": other.id,
                    "customer": a["customer_id"],
                    "service": a["service_id"],
                    **window,
                },
                tenant_context=tenant.id,
            )
    engine.dispose()


def check_invariants(database_url: str) -> dict[str, int]:
    engine = create_engine(database_url, future=True)
    queries = {
        "overlapping_live_jobs_for_one_technician": """
            SELECT count(*) FROM jobs a JOIN jobs b
              ON a.employee_id = b.employee_id AND a.id < b.id
             AND tstzrange(a.scheduled_start, a.scheduled_end) && tstzrange(b.scheduled_start, b.scheduled_end)
            WHERE a.status IN ('SCHEDULED','IN_PROGRESS','COMPLETED') AND b.status IN ('SCHEDULED','IN_PROGRESS','COMPLETED')""",
        "bookings_referencing_another_tenants_customer_or_service": """
            SELECT count(*) FROM bookings b
              JOIN customers c ON c.id = b.customer_id JOIN services s ON s.id = b.service_id
             WHERE c.organization_id <> b.organization_id OR s.organization_id <> b.organization_id""",
        "jobs_assigned_to_another_tenants_technician": """
            SELECT count(*) FROM jobs j JOIN employees e ON e.id = j.employee_id
             WHERE e.organization_id <> j.organization_id""",
        "duplicate_open_bookings": """
            SELECT count(*) FROM (SELECT 1 FROM bookings WHERE status IN ('PENDING','CONFIRMED')
             GROUP BY organization_id, customer_id, service_id, requested_start HAVING count(*) > 1) d""",
        "bookings_without_exactly_one_job": """
            SELECT count(*) FROM bookings b WHERE (SELECT count(*) FROM jobs j WHERE j.booking_id = b.id) <> 1""",
        "cross_tenant_notes_written": "SELECT count(*) FROM job_notes WHERE content = 'x'",
        "customers_renamed_cross_tenant": "SELECT count(*) FROM customers WHERE notes = 'cross-tenant'",
    }
    with Session(engine) as db:
        db.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
        result = {name: int(db.execute(text(sql)).scalar_one()) for name, sql in queries.items()}
    engine.dispose()
    return result


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        return None


def environment(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        postgres = connection.execute(text("SHOW server_version")).scalar_one()
    engine.dispose()
    return {
        "postgres_version": postgres,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", default=str(REPO / "benchmarks/results/tenant_isolation.json"))
    parser.add_argument("--tenants", type=int, default=4)
    parser.add_argument("--technicians", type=int, default=4)
    parser.add_argument("--customers", type=int, default=6)
    parser.add_argument("--slots", type=int, default=6, help="Anchor bookings per technician")
    parser.add_argument("--access-sample", type=int, default=12)
    parser.add_argument("--race-rounds", type=int, default=8)
    parser.add_argument("--race-size", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260914)
    args = parser.parse_args()

    report = run(args)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    summary = report["summary"]
    print(
        f"attempted={summary['attempted']} blocked={summary['blocked']} "
        f"unexpected_successes={summary['unexpected_successes']} server_errors={summary['server_errors']} "
        f"invariant_violations={sum(report['database_invariants_violations'].values())} "
        f"controls_failed={sum(report['controls']['failed'].values())} -> {'PASS' if report['passed'] else 'FAIL'}"
    )
    for name, category in report["categories"].items():
        print(
            f"  {name:<32} {category['attempted']:>5} attempted  {category['blocked']:>5} blocked  {category['unexpected_successes']} unexpected"
        )
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
