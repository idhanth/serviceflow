#!/usr/bin/env bash
# Start/stop the local PostgreSQL + Redis used for development.
# Docker Compose (docker-compose.yml) is the deployment-parity path; this script
# is the no-Docker fallback for machines without admin rights.
#
#   ./scripts/services.sh start|stop|status|reset
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env.sh"

STATE="$ROOT/.localdev"
PGDATA="$STATE/pgdata"
LOGS="$STATE/logs"
mkdir -p "$LOGS"

pg_running() { "$SERVICEFLOW_SERVICES_BIN/pg_isready" -q -h "$PGHOST" -p "$PGPORT" 2>/dev/null; }
redis_running() { "$SERVICEFLOW_SERVICES_BIN/redis-cli" -p "$REDIS_PORT" ping >/dev/null 2>&1; }

start() {
  if [ ! -d "$PGDATA" ]; then
    echo "==> initdb $PGDATA"
    "$SERVICEFLOW_SERVICES_BIN/initdb" -D "$PGDATA" -U "$PGUSER" --encoding=UTF8 --locale=C >"$LOGS/initdb.log" 2>&1
  fi
  if pg_running; then
    echo "==> postgres already running on :$PGPORT"
  else
    echo "==> starting postgres on :$PGPORT"
    "$SERVICEFLOW_SERVICES_BIN/pg_ctl" -D "$PGDATA" -l "$LOGS/postgres.log" \
      -o "-p $PGPORT -k $STATE -c listen_addresses=127.0.0.1" -w start
  fi
  "$SERVICEFLOW_SERVICES_BIN/psql" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname='$PGDATABASE'" | grep -q 1 \
    || "$SERVICEFLOW_SERVICES_BIN/createdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"

  if redis_running; then
    echo "==> redis already running on :$REDIS_PORT"
  else
    echo "==> starting redis on :$REDIS_PORT"
    "$SERVICEFLOW_SERVICES_BIN/redis-server" --port "$REDIS_PORT" --daemonize yes \
      --dir "$STATE" --logfile "$LOGS/redis.log" --save ''
  fi
  status
}

stop() {
  redis_running && "$SERVICEFLOW_SERVICES_BIN/redis-cli" -p "$REDIS_PORT" shutdown nosave 2>/dev/null || true
  [ -d "$PGDATA" ] && "$SERVICEFLOW_SERVICES_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop 2>/dev/null || true
  echo "==> stopped"
}

status() {
  pg_running && echo "postgres  UP    $PGHOST:$PGPORT/$PGDATABASE" || echo "postgres  DOWN"
  redis_running && echo "redis     UP    $PGHOST:$REDIS_PORT" || echo "redis     DOWN"
}

reset() { stop; rm -rf "$PGDATA"; echo "==> wiped $PGDATA"; start; }

case "${1:-status}" in
  start) start ;; stop) stop ;; status) status ;; reset) reset ;;
  *) echo "usage: $0 start|stop|status|reset" >&2; exit 2 ;;
esac
