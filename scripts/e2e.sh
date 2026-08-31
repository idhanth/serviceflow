#!/usr/bin/env bash
# Run the Playwright end-to-end suite against the real stack.
#
#   ./scripts/e2e.sh                 # whole suite
#   ./scripts/e2e.sh customer.spec   # one spec (any playwright filter works)
#   E2E_KEEP=1 ./scripts/e2e.sh      # leave the servers running afterwards
#
# Starts anything that is not already running (API, Celery worker, web) and
# stops only what it started. PostgreSQL, Redis, MinIO and MailPit must be up:
# ./scripts/services.sh start
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env.sh"

LOGS="$ROOT/.localdev/logs"
mkdir -p "$LOGS"
STARTED=()

cleanup() {
  if [ "${E2E_KEEP:-0}" = "1" ]; then
    echo "==> leaving ${#STARTED[@]} process(es) running (E2E_KEEP=1)"
    return
  fi
  for pid in "${STARTED[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

wait_for() { # url, name, attempts
  local url="$1" name="$2" attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "!! $name did not come up at $url" >&2
  return 1
}

echo "==> checking infrastructure"
"$ROOT/scripts/services.sh" status | sed 's/^/    /'
for probe in "http://127.0.0.1:$PGPORT" ""; do :; done
"$SERVICEFLOW_SERVICES_BIN/pg_isready" -q -h "$PGHOST" -p "$PGPORT" || {
  echo "!! PostgreSQL is not running. Run ./scripts/services.sh start" >&2; exit 1; }
"$SERVICEFLOW_SERVICES_BIN/redis-cli" -p "$REDIS_PORT" ping >/dev/null || {
  echo "!! Redis is not running. Run ./scripts/services.sh start" >&2; exit 1; }

# Rate limits are per client address and this whole suite comes from 127.0.0.1.
# Clearing the counters is test-environment hygiene, not a code path: the
# limiter itself stays enabled, and one spec deliberately trips it.
echo "==> clearing rate-limit counters"
"$SERVICEFLOW_SERVICES_BIN/redis-cli" -p "$REDIS_PORT" \
  eval "local k=redis.call('keys','sf:rl:*') for i=1,#k do redis.call('del',k[i]) end return #k" 0 \
  | sed 's/^/    cleared /'

if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "==> api already running"
else
  echo "==> starting api on :8000"
  ( cd "$ROOT/apps/api" && uv run uvicorn serviceflow.main:app --port 8000 --log-level info \
      >"$LOGS/e2e-api.log" 2>&1 & echo $! > "$LOGS/e2e-api.pid" )
  STARTED+=("$(cat "$LOGS/e2e-api.pid")")
  wait_for http://127.0.0.1:8000/health "api"
fi

if pgrep -f "celery.*serviceflow" >/dev/null 2>&1; then
  echo "==> worker already running"
else
  echo "==> starting celery worker"
  ( "$ROOT/scripts/worker.sh" >"$LOGS/e2e-worker.log" 2>&1 & echo $! > "$LOGS/e2e-worker.pid" )
  STARTED+=("$(cat "$LOGS/e2e-worker.pid")")
fi

# A running server is a previous build. Rebuilding every run is a few seconds
# and stops the suite silently testing yesterday's bundle.
if [ "${E2E_REUSE_WEB:-0}" = "1" ] && curl -sf http://127.0.0.1:3000/login >/dev/null 2>&1; then
  echo "==> reusing the running web server (E2E_REUSE_WEB=1)"
else
  pkill -f "next-server" 2>/dev/null || true
  echo "==> building and starting web on :3000"
  ( cd "$ROOT/apps/web" && npm run build >"$LOGS/e2e-web-build.log" 2>&1 ) || {
    echo "!! web build failed, see $LOGS/e2e-web-build.log" >&2; exit 1; }
  ( cd "$ROOT/apps/web" && npm run start >"$LOGS/e2e-web.log" 2>&1 & echo $! > "$LOGS/e2e-web.pid" )
  STARTED+=("$(cat "$LOGS/e2e-web.pid")")
  wait_for http://127.0.0.1:3000/login "web" 90
fi

echo "==> running playwright"
cd "$ROOT/apps/web"
npx playwright test "$@"
