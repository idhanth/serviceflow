"""Capture the query plans behind the load test's endpoints.

    ./scripts/load-test.sh reset
    uv run --project apps/api python benchmarks/load/explain_queries.py

Signs in as one load tenant's dispatcher and calls the same endpoints the k6
scenario calls, through the real application (routes, auth, tenant context),
while recording every SELECT the API sends to PostgreSQL. Each distinct
statement is then run again under `EXPLAIN (ANALYZE, BUFFERS)` with the same
parameters and the same row level security context, and the plans are written
to benchmarks/results/query_plans.txt.

Plans are read for their shape - which index is used, whether anything is
sequentially scanned or sorted in memory - not quoted as timings.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "benchmarks/load/.dataset.json"
OUTPUT = REPO / "benchmarks/results/query_plans.txt"
DATABASE_URL = os.environ.get(
    "LOAD_DATABASE_URL", "postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433/serviceflow_load"
)

os.environ.update(
    {
        "DATABASE_URL": DATABASE_URL,
        "RATE_LIMITING_ENABLED": "false",
        "JWT_SECRET": os.environ.get("JWT_SECRET", "load-test-secret-that-is-long-enough-1234"),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/4"),
        "SERVICEFLOW_BROKER_URL": "memory://",
        "SERVICEFLOW_RESULT_BACKEND": "cache+memory://",
        "ENVIRONMENT": "local",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, text  # noqa: E402

from serviceflow.db.session import get_engine  # noqa: E402
from serviceflow.main import app  # noqa: E402

ENDPOINTS = [
    ("GET /bookings", "bookings?page=2&page_size=25&status=CONFIRMED"),
    ("GET /bookings (upcoming)", "bookings?page=1&page_size=25&timeframe=upcoming"),
    ("GET /jobs", "jobs?page=1&page_size=25&status=SCHEDULED&timeframe=upcoming"),
    ("GET /jobs (needs technician)", "jobs?page=1&page_size=25&status=NEW&timeframe=upcoming"),
    ("GET /customers", "customers?page=5&page_size=25"),
    ("GET /schedule", f"schedule?start={dt.date.today().isoformat()}"),
    ("GET /dashboard", "dashboard"),
]


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    tenant = manifest["tenants"][0]
    captured: list[tuple[str, Any]] = []
    recording = {"on": False}

    @event.listens_for(get_engine(), "before_cursor_execute")
    def _record(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        if recording["on"] and statement.lstrip().upper().startswith("SELECT") and "set_config" not in statement:
            captured.append((statement, parameters))

    sections: list[str] = []
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": tenant["accounts"]["dispatcher"], "password": manifest["password"]},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for label, path in ENDPOINTS:
            captured.clear()
            recording["on"] = True
            response = client.get(f"/api/v1/{path}", headers=headers)
            recording["on"] = False
            response.raise_for_status()

            seen: set[str] = set()
            for statement, parameters in captured:
                if statement in seen:
                    continue
                seen.add(statement)
                with get_engine().connect() as conn:
                    conn.execute(text("SELECT set_config('app.organization_id', :org, true)"), {"org": tenant["id"]})
                    plan = conn.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS) {statement}", parameters).scalars()
                    body = "\n".join(plan)
                    conn.rollback()
                sql = re.sub(r"\s+", " ", statement).strip()
                sections.append(f"-- {label}  ({path})\n-- {sql}\n{body}\n")

    header = (
        "Query plans for the load test's endpoints, captured by benchmarks/load/explain_queries.py\n"
        f"against the load dataset ({manifest['totals']['bookings']:,} bookings, "
        f"{manifest['totals']['tenants']} tenants), as tenant {tenant['slug']}'s dispatcher, "
        f"on {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}.\n"
        "Timings in these plans come from one execution and are not benchmark results.\n\n"
    )
    OUTPUT.write_text(header + "\n".join(sections))
    print(f"wrote {len(sections)} plans to {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
