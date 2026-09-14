#!/usr/bin/env bash
# Run the tenant-isolation benchmark against a throwaway database and API.
#
#   ./scripts/bench-isolation.sh                       # writes benchmarks/results/tenant_isolation.json
#   OUTPUT=/tmp/iso.json ./scripts/bench-isolation.sh  # anywhere else (CI uses this)
#
# Never touches the development database: it drops and rebuilds serviceflow_bench,
# runs an API on :8200 against it with rate limiting off (the benchmark measures
# refusals by the product's rules, not by the limiter), and stops it afterwards.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/scripts/env.sh" ] && source "$ROOT/scripts/env.sh" || true

DB_BASE="${DB_BASE:-postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433}"
BENCH_DB="${BENCH_DB:-serviceflow_bench}"
PORT="${BENCH_PORT:-8200}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6380/3}"
OUTPUT="${OUTPUT:-$ROOT/benchmarks/results/tenant_isolation.json}"
DSN="$DB_BASE/$BENCH_DB"
LOG="${TMPDIR:-/tmp}/serviceflow-bench-api.log"

cd "$ROOT/apps/api"

echo "==> rebuilding $BENCH_DB"
uv run python - "$DB_BASE" "$BENCH_DB" <<'PY'
import sys
import psycopg
base, name = sys.argv[1].replace("postgresql+psycopg://", "postgresql://"), sys.argv[2]
with psycopg.connect(f"{base}/postgres", autocommit=True) as conn:
    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
    conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    conn.execute(f'CREATE DATABASE "{name}"')
PY
DATABASE_URL="$DSN" uv run alembic upgrade head >/dev/null

echo "==> starting api on :$PORT"
DATABASE_URL="$DSN" REDIS_URL="$REDIS_URL" RATE_LIMITING_ENABLED=false \
  SERVICEFLOW_BROKER_URL="memory://" SERVICEFLOW_RESULT_BACKEND="cache+memory://" \
  JWT_SECRET="${JWT_SECRET:-benchmark-secret-that-is-long-enough-1234}" ENVIRONMENT=local \
  uv run uvicorn serviceflow.main:app --port "$PORT" --workers 2 --log-level warning >"$LOG" 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true; wait $API_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { echo "api did not start; see $LOG" >&2; exit 1; }

echo "==> running benchmark"
uv run python "$ROOT/benchmarks/tenant_isolation/run.py" \
  --base-url "http://127.0.0.1:$PORT" --database-url "$DSN" --output "$OUTPUT" "$@"
