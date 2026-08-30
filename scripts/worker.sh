#!/usr/bin/env bash
# Run the Celery worker (with the beat scheduler embedded, which is fine for a
# single-node development setup - production runs beat as its own process).
#
#   ./scripts/worker.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/env.sh"

cd "$ROOT/apps/api"
exec uv run celery -A serviceflow.worker.celery_app worker \
  --beat --loglevel="${CELERY_LOGLEVEL:-info}" --concurrency=2
