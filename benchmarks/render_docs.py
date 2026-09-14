"""Render benchmark numbers into the docs, straight from the committed results.

    uv run --project apps/api python benchmarks/render_docs.py          # rewrite the marked sections
    uv run --project apps/api python benchmarks/render_docs.py --check  # fail if the docs have drifted

Every figure in README.md and docs/benchmarks.md that comes from a benchmark sits
between markers like

    <!-- benchmark:isolation-summary:start -->
    ...generated...
    <!-- benchmark:isolation-summary:end -->

and is generated here from benchmarks/results/*.json. Nobody types a benchmark
number into the docs by hand, and tests/test_benchmark_claims.py runs --check so
an edited number, or a rerun whose docs were not regenerated, fails CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "benchmarks/results"
DOCS = [REPO / "README.md", REPO / "docs/benchmarks.md"]

CATEGORY_LABELS = {
    "exact_duplicate_booking": "Exact duplicate bookings",
    "overlapping_employee_booking": "Overlapping technician bookings",
    "concurrent_double_booking": "Concurrent double-booking races (losing requests)",
    "cross_tenant_customer": "Cross-tenant customer in a booking",
    "cross_tenant_employee": "Cross-tenant technician in a booking or assignment",
    "cross_tenant_service": "Cross-tenant service in a booking",
    "cross_tenant_resource_access": "Reading or changing another tenant's records by id",
    "unauthorized_role": "Actions outside the caller's role",
    "database_level_bypass": "Raw SQL writes that skip the API",
}


def load(name: str) -> dict[str, Any] | None:
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def n(value: float | int) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def isolation_summary(r: dict[str, Any]) -> str:
    s = r["summary"]
    violations = sum(r["database_invariants_violations"].values())
    controls = sum(r["controls"]["succeeded"].values())
    return "\n".join(
        [
            "| Invalid attempts | Blocked | Unexpected successes | Server errors | Invariant violations |",
            "| ---: | ---: | ---: | ---: | ---: |",
            f"| {n(s['attempted'])} | {n(s['blocked'])} | {n(s['unexpected_successes'])} "
            f"| {n(s['server_errors'])} | {n(violations)} |",
            "",
            f"Alongside the attacks, {n(controls)} legitimate control writes succeeded "
            f"(result: **{'PASS' if r['passed'] else 'FAIL'}**, commit `{r.get('git_commit') or 'n/a'}`, "
            f"{r['generated_at']}).",
        ]
    )


def isolation_categories(r: dict[str, Any]) -> str:
    rows = [
        "| Category | Attempted | Blocked | Unexpected | How it was refused |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for key, label in CATEGORY_LABELS.items():
        c = r["categories"][key]
        refusals = ", ".join(
            f"`{code}` {count:,}" for code, count in sorted(c["refusals"].items(), key=lambda kv: -kv[1])
        )
        rows.append(
            f"| {label} | {n(c['attempted'])} | {n(c['blocked'])} | {n(c['unexpected_successes'])} | {refusals} |"
        )
    return "\n".join(rows)


def load_summary(r: dict[str, Any]) -> str:
    res, cfg, env = r["results"], r["configuration"], r["environment"]
    lat = res["latency_ms"]
    machine = env["machine"]
    return "\n".join(
        [
            "| Throughput | p50 | p95 | p99 | Error rate | Requests |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {n(res['requests_per_second'])} req/s | {n(lat['p50'])} ms | {n(lat['p95'])} ms "
            f"| {n(lat['p99'])} ms | {res['error_rate'] * 100:.2f}% | {n(res['total_requests'])} |",
            "",
            f"{cfg['virtual_users']} concurrent virtual users for {cfg['duration']}, no think time, against "
            f"{n(r['dataset']['tenants'])} tenants, {n(r['dataset']['bookings'])} bookings and "
            f"{n(r['dataset']['jobs'])} jobs. {cfg['uvicorn_workers']} API workers, pool "
            f"{cfg['pool']['pool_size']} + {cfg['pool']['max_overflow']} per worker; peak "
            f"{r['database_connections']['peak_total']} PostgreSQL connections. "
            f"{machine.get('cpu', machine['arch'])}, {machine.get('memory_gb', '?')} GB, "
            f"PostgreSQL {env['postgres_version'].split()[0]}, Redis {env.get('redis_version') or 'n/a'}; "
            f"everything on one machine (commit `{r.get('git_commit') or 'n/a'}`, {r['generated_at']}).",
        ]
    )


def load_endpoints(r: dict[str, Any]) -> str:
    rows = ["| Endpoint | p50 | p95 | p99 |", "| --- | ---: | ---: | ---: |"]
    for name, v in r["per_endpoint_latency_ms"].items():
        rows.append(f"| `{name}` | {n(v['p50'])} ms | {n(v['p95'])} ms | {n(v['p99'])} ms |")
    return "\n".join(rows)


def load_configuration(r: dict[str, Any]) -> str:
    cfg, env, ds, db = r["configuration"], r["environment"], r["dataset"], r["database_connections"]
    machine = env["machine"]
    pool = cfg["pool"]
    return "\n".join(
        [
            "| | |",
            "| --- | --- |",
            f"| Hardware | {machine.get('cpu', machine['arch'])}, {machine['logical_cpus']} logical CPUs, {machine.get('memory_gb', '?')} GB RAM ({machine['os']}) |",
            f"| Topology | {env['topology']} |",
            f"| PostgreSQL | {env['postgres_version']} (max_connections {db['postgres_max_connections']}) |",
            f"| Redis | {env.get('redis_version') or 'n/a'} |",
            f"| Load generator | {env['k6']} |",
            f"| Dataset | {n(ds['tenants'])} tenants, {n(ds['technicians'])} technicians, {n(ds['customers'])} customers, "
            f"{n(ds['services'])} services, {n(ds['bookings'])} bookings, {n(ds['jobs'])} jobs, {n(ds['users'])} users |",
            f"| Concurrency | {cfg['virtual_users']} virtual users, {cfg['think_time']} |",
            f"| Duration | {cfg['duration']} |",
            f"| API | {cfg['uvicorn_workers']} uvicorn workers, rate limiting {cfg['rate_limiting']} |",
            f"| Pool (per worker) | pool_size={pool['pool_size']}, max_overflow={pool['max_overflow']}, "
            f"pool_timeout={pool['pool_timeout_seconds']}s, pool_recycle={pool['pool_recycle_seconds']}s, "
            f"pre_ping, at most {pool['max_connections_from_api']} connections from the API |",
            f"| Connections observed | peak {db['peak_total']} total, peak {db['peak_active']} active, mean {db['mean_active']} active |",
        ]
    )


def load_tuning(runs: list[dict[str, Any]], chosen: dict[str, Any] | None) -> str:
    rows = [
        "| Workers | Pool per worker | Max API connections | Throughput | p50 | p95 | p99 | Errors | Peak connections |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def key(r: dict[str, Any]) -> tuple[int, int, int]:
        pool = r["configuration"]["pool"]
        return (r["configuration"]["uvicorn_workers"], pool["pool_size"], pool["max_overflow"])

    for r in sorted(runs, key=key):
        res, cfg = r["results"], r["configuration"]
        pool, lat = cfg["pool"], res["latency_ms"]
        rows.append(
            f"| {cfg['uvicorn_workers']} | {pool['pool_size']} + {pool['max_overflow']} | {pool['max_connections_from_api']} "
            f"| {n(res['requests_per_second'])} req/s | {n(lat['p50'])} ms | {n(lat['p95'])} ms | {n(lat['p99'])} ms "
            f"| {res['error_rate'] * 100:.2f}% | {r['database_connections']['peak_total']} |"
        )
    first = runs[0]["configuration"] if runs else None
    if first:
        rows += [
            "",
            f"Each row is one run of {first['virtual_users']} virtual users for {first['duration']} against a freshly "
            f"rebuilt dataset, from `benchmarks/results/tuning/`.",
        ]
    if chosen:
        pool = chosen["configuration"]["pool"]
        rows[-1] += (
            f" The headline result uses {chosen['configuration']['uvicorn_workers']} workers with a pool of "
            f"{pool['pool_size']} + {pool['max_overflow']}, measured again in its own run."
        )
    return "\n".join(rows)


def load_repeats(runs: list[tuple[str, dict[str, Any]]], chosen: dict[str, Any] | None) -> str:
    rows = [
        "| Run | Throughput | p50 | p95 | p99 | Errors | Requests | Peak connections | Published |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for name, r in runs:
        res, lat = r["results"], r["results"]["latency_ms"]
        published = "yes" if chosen and r["raw_summary"] == chosen["raw_summary"] else ""
        rows.append(
            f"| {name} | {n(res['requests_per_second'])} req/s | {n(lat['p50'])} ms | {n(lat['p95'])} ms "
            f"| {n(lat['p99'])} ms | {res['error_rate'] * 100:.2f}% | {n(res['total_requests'])} "
            f"| {r['database_connections']['peak_total']} | {published} |"
        )
    return "\n".join(rows)


def resume_bullets(iso: dict[str, Any], load_result: dict[str, Any]) -> str:
    s = iso["summary"]
    res = load_result["results"]
    tenants = iso["configuration"]["tenants"]
    return "\n".join(
        [
            "- Built multi-tenant booking, scheduling and job-tracking workflows for 7 user roles "
            "(platform admin, owner, manager, dispatcher, technician, customer, read-only analyst) "
            "in one FastAPI + Next.js platform.",
            f"- Blocked all {n(s['attempted'])} tested duplicate, overlapping, cross-tenant and unauthorized "
            f"booking attempts ({n(s['unexpected_successes'])} unexpected successes across {tenants} tenants) "
            "by enforcing isolation in PostgreSQL with composite tenant foreign keys, an exclusion constraint "
            "and row level security.",
            f"- Sustained {n(res['requests_per_second'])} req/s at {n(res['latency_ms']['p95'])} ms p95 "
            f"with {res['error_rate'] * 100:.2f}% errors in k6 load tests of an authenticated read/write mix "
            f"over {n(load_result['dataset']['bookings'])} bookings, after profiling endpoints and "
            "tuning connection pools.",
        ]
    )


def sections() -> dict[str, str]:
    iso, load_result = load("tenant_isolation"), load("load_test")
    rendered: dict[str, str] = {}
    if iso:
        rendered["isolation-summary"] = isolation_summary(iso)
        rendered["isolation-categories"] = isolation_categories(iso)
    if load_result:
        rendered["load-summary"] = load_summary(load_result)
        rendered["load-endpoints"] = load_endpoints(load_result)
        rendered["load-configuration"] = load_configuration(load_result)
    final = [(p.stem, json.loads(p.read_text())) for p in sorted((RESULTS / "final").glob("run-*.json"))]
    if final:
        rendered["load-repeats"] = load_repeats(final, load_result)
    tuning = [json.loads(p.read_text()) for p in sorted((RESULTS / "tuning").glob("*.json"))]
    if tuning:
        rendered["load-tuning"] = load_tuning(tuning, load_result)
    if iso and load_result:
        rendered["resume-bullets"] = resume_bullets(iso, load_result)
    return rendered


def apply(text: str, rendered: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in rendered:
            raise SystemExit(f"no benchmark result available for section '{name}'")
        return f"<!-- benchmark:{name}:start -->\n{rendered[name]}\n<!-- benchmark:{name}:end -->"

    return re.sub(
        r"<!-- benchmark:([a-z-]+):start -->.*?<!-- benchmark:\1:end -->",
        replace,
        text,
        flags=re.DOTALL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if any doc differs from the results")
    args = parser.parse_args(argv)
    rendered = sections()
    drifted = []
    for path in DOCS:
        if not path.exists():
            continue
        current = path.read_text()
        updated = apply(current, rendered)
        if updated != current:
            if args.check:
                drifted.append(str(path.relative_to(REPO)))
            else:
                path.write_text(updated)
                print(f"updated {path.relative_to(REPO)}")
    if drifted:
        print("benchmark numbers in these docs do not match benchmarks/results: " + ", ".join(drifted))
        print("run: uv run --project apps/api python benchmarks/render_docs.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
