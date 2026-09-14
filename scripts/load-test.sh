#!/usr/bin/env bash
# Build the load-test dataset and run the k6 mixed workload against it.
#
#   ./scripts/load-test.sh reset                      # (re)build serviceflow_load: 25 tenants, 50k bookings
#   ./scripts/load-test.sh run 100 60s                # 100 virtual users for 60s -> benchmarks/results/load_test.json
#   WORKERS=4 POOL_SIZE=10 MAX_OVERFLOW=5 ./scripts/load-test.sh run 100 60s
#
# Never points at the development database. Rate limiting is off for the API it
# starts, so the run measures the system serving traffic rather than the limiter
# refusing it; the limiter has its own tests against real Redis.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/scripts/env.sh" ] && source "$ROOT/scripts/env.sh" || true

DB_BASE="${DB_BASE:-postgresql+psycopg://serviceflow:serviceflow@127.0.0.1:5433}"
LOAD_DB="${LOAD_DB:-serviceflow_load}"
cd "$ROOT/apps/api"

reset() {
  echo "==> rebuilding $LOAD_DB"
  uv run python - "$DB_BASE" "$LOAD_DB" <<'PY'
import sys
import psycopg
base, name = sys.argv[1].replace("postgresql+psycopg://", "postgresql://"), sys.argv[2]
with psycopg.connect(f"{base}/postgres", autocommit=True) as conn:
    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
    conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    conn.execute(f'CREATE DATABASE "{name}"')
PY
  DATABASE_URL="$DB_BASE/$LOAD_DB" uv run alembic upgrade head >/dev/null
  uv run python "$ROOT/benchmarks/load/seed_dataset.py" --database-url "$DB_BASE/$LOAD_DB" \
    --tenants "${TENANTS:-25}" --technicians "${TECHNICIANS:-20}" --customers "${CUSTOMERS:-400}" \
    --bookings "${BOOKINGS:-2000}"
}

case "${1:-run}" in
  reset)
    reset
    ;;
  run)
    # Every measured run starts from the same freshly built dataset, so one run's
    # bookings and job updates cannot collide with or skew the next.
    [ "${KEEP_DATA:-0}" = "1" ] && [ -f "$ROOT/benchmarks/load/.dataset.json" ] || reset
    uv run python "$ROOT/benchmarks/load/run.py" --vus "${2:-100}" --duration "${3:-60s}" \
      --workers "${WORKERS:-4}" --pool-size "${POOL_SIZE:-10}" --max-overflow "${MAX_OVERFLOW:-5}" \
      --pool-timeout "${POOL_TIMEOUT:-5}" --db-base "$DB_BASE" --database "$LOAD_DB" \
      --label "${LABEL:-mixed}" ${OUTPUT:+--output "$OUTPUT"}
    ;;
  *)
    echo "usage: $0 reset | run [vus] [duration]" >&2
    exit 2
    ;;
esac
