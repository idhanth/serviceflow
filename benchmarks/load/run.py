"""Run the k6 load test and write benchmarks/results/load_test.json.

    uv run --project apps/api python benchmarks/load/run.py --vus 100 --duration 60s

Starts an API against the load database with the requested worker count and
connection-pool settings, samples PostgreSQL's connection count while k6 runs,
and merges k6's raw summary with everything needed to reproduce the number:
hardware, versions, dataset size, pool configuration and duration.

`scripts/load-test.sh` wraps this with building the dataset. The raw k6 summary
is kept next to the report, so the headline figures can be checked against it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "benchmarks/results"


def sample_connections(dsn: str, database: str, stop: threading.Event, samples: list[dict[str, int]]) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        while not stop.is_set():
            row = conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE state = 'active'),"
                " count(*) FILTER (WHERE wait_event_type = 'Lock')"
                " FROM pg_stat_activity WHERE datname = %s",
                (database,),
            ).fetchone()
            samples.append({"total": int(row[0]), "active": int(row[1]), "waiting_on_lock": int(row[2])})  # type: ignore[index]
            stop.wait(1.0)


def machine() -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "logical_cpus": os.cpu_count(),
    }
    if platform.system() == "Darwin":
        info["cpu"] = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        info["memory_gb"] = round(int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)) / 2**30)
    else:
        try:
            info["cpu"] = next(
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if "model name" in line
            )
            info["memory_gb"] = round(int(Path("/proc/meminfo").read_text().split()[1]) / 2**20)
        except (StopIteration, OSError):
            pass
    return info


def metric(summary: dict[str, Any], name: str) -> dict[str, Any]:
    return summary["metrics"].get(name, {})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vus", type=int, default=100)
    parser.add_argument("--duration", default="60s")
    parser.add_argument("--workers", type=int, default=4, help="uvicorn worker processes")
    parser.add_argument("--pool-size", type=int, default=10)
    parser.add_argument("--max-overflow", type=int, default=5)
    parser.add_argument("--pool-timeout", type=int, default=5)
    parser.add_argument("--pool-recycle", type=int, default=1800)
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--db-base", default="postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433")
    parser.add_argument("--database", default="serviceflow_load")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/4"))
    parser.add_argument("--k6", default=shutil.which("k6") or str(Path.home() / ".local/opt/k6/k6"))
    parser.add_argument("--label", default="mixed")
    parser.add_argument("--output", default=str(RESULTS / "load_test.json"))
    args = parser.parse_args()

    dsn = f"{args.db_base}/{args.database}"
    plain = dsn.replace("postgresql+psycopg://", "postgresql://")
    manifest = json.loads((REPO / "benchmarks/load/.dataset.json").read_text())
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = RESULTS / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_summary = raw_dir / f"load_{args.label}_{args.vus}vu_{stamp}.json"

    env = {
        **os.environ,
        "DATABASE_URL": dsn,
        "REDIS_URL": args.redis_url,
        "RATE_LIMITING_ENABLED": "false",
        "DATABASE_POOL_SIZE": str(args.pool_size),
        "DATABASE_MAX_OVERFLOW": str(args.max_overflow),
        "DATABASE_POOL_TIMEOUT": str(args.pool_timeout),
        "DATABASE_POOL_RECYCLE": str(args.pool_recycle),
        "SERVICEFLOW_BROKER_URL": os.environ.get("LOAD_BROKER_URL", "memory://"),
        "SERVICEFLOW_RESULT_BACKEND": "cache+memory://",
        "JWT_SECRET": os.environ.get("JWT_SECRET", "load-test-secret-that-is-long-enough-1234"),
        "ENVIRONMENT": "local",
        "LOG_LEVEL": "WARNING",
    }
    api = subprocess.Popen(
        ["uv", "run", "uvicorn", "serviceflow.main:app", "--port", str(args.port), "--workers", str(args.workers),
         "--log-level", "warning", "--no-access-log"],
        cwd=REPO / "apps/api", env=env, stdout=subprocess.DEVNULL, stderr=open(raw_dir / "api.log", "w"),  # noqa: SIM115
        start_new_session=True,
    )  # fmt: skip
    try:
        for _ in range(90):
            try:
                if httpx.get(f"http://127.0.0.1:{args.port}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise SystemExit("load API did not start; see benchmarks/results/raw/api.log")

        with psycopg.connect(plain) as conn:
            pg_version = conn.execute("SHOW server_version").fetchone()[0]  # type: ignore[index]
            max_connections = int(conn.execute("SHOW max_connections").fetchone()[0])  # type: ignore[index]
            conn.execute("SELECT set_config('app.rls_bypass', 'on', false)")
            counts = {
                table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # type: ignore[index]
                for table in (
                    "organizations",
                    "employees",
                    "customers",
                    "services",
                    "bookings",
                    "jobs",
                )
            }
        redis_version = httpx.get(f"http://127.0.0.1:{args.port}/health").json()  # reachable check only
        redis_info = subprocess.run(
            ["redis-cli", "-u", args.redis_url, "INFO", "server"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        redis_server = next(
            (line.split(":", 1)[1].strip() for line in redis_info.splitlines() if line.startswith("redis_version")),
            None,
        )
        k6_version = subprocess.run([args.k6, "version"], capture_output=True, text=True, check=False).stdout.strip()

        stop, samples = threading.Event(), []  # type: ignore[var-annotated]
        sampler = threading.Thread(target=sample_connections, args=(plain, args.database, stop, samples), daemon=True)
        sampler.start()
        started = time.perf_counter()
        result = subprocess.run(
            [args.k6, "run", "--quiet", f"--summary-export={raw_summary}", str(REPO / "benchmarks/load/mixed.js")],
            env={**os.environ, "LOAD_API_URL": f"http://127.0.0.1:{args.port}", "VUS": str(args.vus),
                 "DURATION": args.duration, "DATASET_MANIFEST": str(REPO / "benchmarks/load/.dataset.json")},
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        elapsed = time.perf_counter() - started
        (raw_dir / "k6.log").write_text(result.stdout + result.stderr)
        stop.set()
        sampler.join(timeout=5)
        if not raw_summary.exists():
            raise SystemExit(f"k6 failed:\n{result.stdout}\n{result.stderr}")
    finally:
        os.killpg(api.pid, signal.SIGTERM)
        api.wait(timeout=30)

    summary = json.loads(raw_summary.read_text())
    duration = metric(summary, "http_req_duration")
    failed = metric(summary, "http_req_failed")
    requests = metric(summary, "http_reqs")
    iterations = metric(summary, "iterations")
    endpoints = {
        key.split("{name:", 1)[1].rstrip("}"): value
        for key, value in summary["metrics"].items()
        if key.startswith("http_req_duration{name:")
    }
    checks = summary.get("root_group", {}).get("checks", {})

    report = {
        "benchmark": "load_test",
        "scenario": "mixed staff workload: 25% GET /bookings, 20% GET /jobs, 15% GET /customers, "
        "15% GET /schedule, 10% POST /bookings, 10% PATCH /jobs, 5% GET /dashboard",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        or None,
        "results": {
            "requests_per_second": round(requests.get("rate", 0), 1),
            "total_requests": int(requests.get("count", 0)),
            "iterations": int(iterations.get("count", 0)),
            "latency_ms": {
                "avg": round(duration.get("avg", 0), 1),
                "p50": round(duration.get("med", 0), 1),
                "p90": round(duration.get("p(90)", 0), 1),
                "p95": round(duration.get("p(95)", 0), 1),
                "p99": round(duration.get("p(99)", 0), 1),
                "max": round(duration.get("max", 0), 1),
            },
            "error_rate": round(failed.get("value", 0), 6),
            "failed_requests": int(failed.get("passes", 0)),
            "checks": {name: {"passes": c.get("passes"), "fails": c.get("fails")} for name, c in checks.items()},
        },
        "per_endpoint_latency_ms": {
            name: {
                "p50": round(v.get("med", 0), 1),
                "p95": round(v.get("p(95)", 0), 1),
                "p99": round(v.get("p(99)", 0), 1),
            }
            for name, v in sorted(endpoints.items())
            if name not in {"setup", "login"}
        },
        "database_connections": {
            "peak_total": max((s["total"] for s in samples), default=0),
            "peak_active": max((s["active"] for s in samples), default=0),
            "peak_waiting_on_lock": max((s["waiting_on_lock"] for s in samples), default=0),
            "mean_active": round(sum(s["active"] for s in samples) / len(samples), 1) if samples else 0,
            "postgres_max_connections": max_connections,
            "samples": len(samples),
        },
        "configuration": {
            "virtual_users": args.vus,
            "duration": args.duration,
            "measured_wall_seconds": round(elapsed, 1),
            "think_time": "none (closed loop)",
            "uvicorn_workers": args.workers,
            "pool": {
                "pool_size": args.pool_size,
                "max_overflow": args.max_overflow,
                "pool_timeout_seconds": args.pool_timeout,
                "pool_recycle_seconds": args.pool_recycle,
                "pool_pre_ping": True,
                "max_connections_from_api": args.workers * (args.pool_size + args.max_overflow),
            },
            "rate_limiting": "off (the limiter is tested separately)",
            "celery_broker": "in-memory (email dispatch is asynchronous and not part of the request path)",
        },
        "dataset": {**manifest["totals"], "database_row_counts": counts},
        "environment": {
            "machine": machine(),
            "postgres_version": pg_version,
            "redis_version": redis_server,
            "k6": k6_version,
            "python": platform.python_version(),
            "topology": "API, PostgreSQL, Redis and k6 on the same machine",
        },
        "raw_summary": str(raw_summary.relative_to(REPO)),
    }
    _ = redis_version
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    r = report["results"]
    print(
        f"{r['requests_per_second']} req/s  p50 {r['latency_ms']['p50']} ms  p95 {r['latency_ms']['p95']} ms  "
        f"p99 {r['latency_ms']['p99']} ms  errors {r['error_rate'] * 100:.2f}%  "
        f"peak db connections {report['database_connections']['peak_total']}"
    )


if __name__ == "__main__":
    main()
