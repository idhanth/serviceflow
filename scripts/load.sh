#!/usr/bin/env bash
# Run a k6 load scenario against an isolated load environment.
#
#   ./scripts/load.sh read-heavy 100 60s
#   ./scripts/load.sh write-heavy 500 60s
#   ./scripts/load.sh mixed 100 60s
#   ./scripts/load.sh invariants          # post-run database checks only
#   ./scripts/load.sh reset               # rebuild the load database
#
# Deliberately never points at the development database: it builds and seeds
# `serviceflow_load` and runs a second API on :8100 against it, so a run cannot
# disturb the demo data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env.sh"

LOAD_DB="${LOAD_DB:-serviceflow_load}"
LOAD_PORT="${LOAD_PORT:-8100}"
LOAD_DSN="postgresql+psycopg://$(whoami)@127.0.0.1:${PGPORT}/${LOAD_DB}"
K6="${K6_BIN:-$HOME/.local/opt/k6/k6}"
LOGS="$ROOT/.localdev/logs"
mkdir -p "$LOGS" "$ROOT/load/results"

psql_load() { "$SERVICEFLOW_SERVICES_BIN/psql" -h "$PGHOST" -p "$PGPORT" -d "$LOAD_DB" "$@"; }

build_database() {
  echo "==> rebuilding $LOAD_DB"
  "$SERVICEFLOW_SERVICES_BIN/psql" -h "$PGHOST" -p "$PGPORT" -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$LOAD_DB';" >/dev/null
  "$SERVICEFLOW_SERVICES_BIN/psql" -h "$PGHOST" -p "$PGPORT" -d postgres \
    -c "DROP DATABASE IF EXISTS $LOAD_DB;" -c "CREATE DATABASE $LOAD_DB;" >/dev/null
  ( cd "$ROOT/apps/api" && DATABASE_URL="$LOAD_DSN" uv run alembic upgrade head >/dev/null )
  ( cd "$ROOT/apps/api" && DATABASE_URL="$LOAD_DSN" uv run python -m serviceflow.db.seed | tail -1 )
}

start_api() {
  if curl -sf "http://127.0.0.1:$LOAD_PORT/health" >/dev/null 2>&1; then
    echo "==> load api already running on :$LOAD_PORT"
    return
  fi
  echo "==> starting load api on :$LOAD_PORT"
  # Rate limiting is off for load runs on purpose: with it on the run would
  # measure the limiter refusing traffic rather than the system serving it.
  # The limiter's own behaviour is covered by tests/test_stress_ratelimit.py.
  # Fully detached, including stdin: a background child still holding this
  # script's pipes would keep the whole command alive after k6 finished.
  # Pool sizing is part of what a load run measures, so it is settable here.
  ( cd "$ROOT/apps/api" && DATABASE_URL="$LOAD_DSN" RATE_LIMITING_ENABLED=false \
      DATABASE_POOL_SIZE="${LOAD_POOL_SIZE:-10}" \
      DATABASE_MAX_OVERFLOW="${LOAD_MAX_OVERFLOW:-20}" \
      nohup uv run uvicorn serviceflow.main:app --port "$LOAD_PORT" --log-level warning \
      --workers "${LOAD_WORKERS:-1}" \
      </dev/null >"$LOGS/load-api.log" 2>&1 & echo $! >"$LOGS/load-api.pid" \
  ) </dev/null >/dev/null 2>&1
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$LOAD_PORT/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "!! the load api did not start; see $LOGS/load-api.log" >&2
  exit 1
}

stop_api() {
  # By pattern as well as by pid: nohup'd children do not always match the pid
  # the subshell recorded, and a stale process would silently serve the next
  # run with the previous configuration.
  [ -f "$LOGS/load-api.pid" ] && kill "$(cat "$LOGS/load-api.pid")" 2>/dev/null || true
  pkill -f "uvicorn serviceflow.main:app --port $LOAD_PORT" 2>/dev/null || true
  rm -f "$LOGS/load-api.pid"
  sleep 1
}

case "${1:-mixed}" in
  reset)
    build_database
    ;;
  invariants)
    psql_load -f "$ROOT/load/invariants.sql"
    ;;
  stop)
    stop_api
    ;;
  read-heavy|write-heavy|mixed)
    SCENARIO="$1"
    # A changed pool or worker count needs a fresh process, or the run measures
    # the previous configuration.
    if [ -n "${LOAD_POOL_SIZE:-}" ] || [ -n "${LOAD_WORKERS:-}" ]; then stop_api; fi
    VUS="${2:-100}"
    DURATION="${3:-60s}"
    [ -x "$K6" ] || { echo "!! k6 not found at $K6" >&2; exit 1; }
    psql_load -c "select 1" >/dev/null 2>&1 || build_database
    start_api
    STAMP="$(date +%Y%m%d-%H%M%S)"
    OUT="$ROOT/load/results/${SCENARIO}-${VUS}vu-${STAMP}.json"
    echo "==> $SCENARIO, $VUS VUs, $DURATION -> $(basename "$OUT")"
    LOAD_API_URL="http://127.0.0.1:$LOAD_PORT" VUS="$VUS" DURATION="$DURATION" \
      "$K6" run --summary-export="$OUT" "$ROOT/load/$SCENARIO.js" 2>&1 | tail -30
    ;;
  *)
    echo "usage: $0 [read-heavy|write-heavy|mixed] [vus] [duration] | reset | invariants | stop" >&2
    exit 2
    ;;
esac
