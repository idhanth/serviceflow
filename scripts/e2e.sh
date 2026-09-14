#!/usr/bin/env bash
# Run the Playwright end-to-end suite against the Docker Compose stack.
#
#   docker compose up --build -d && ./scripts/e2e.sh
#   ./scripts/e2e.sh 03-jobs          # one spec (any playwright filter works)
#
# The suite signs every demo role in once (e2e/support/global-setup.ts). Sign-in
# is rate limited per client address and the limiter stays on, so the counters
# are cleared first when the stack's Redis is reachable through Compose.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="${E2E_BASE_URL:-http://localhost:3000}"

curl -sf "$WEB/login" >/dev/null || {
  echo "!! nothing answering at $WEB - start the stack with: docker compose up --build -d" >&2
  exit 1
}

if command -v docker >/dev/null 2>&1 && docker compose -f "$ROOT/docker-compose.yml" ps redis >/dev/null 2>&1; then
  docker compose -f "$ROOT/docker-compose.yml" exec -T redis redis-cli \
    eval "local k=redis.call('keys','sf:rl:*') for i=1,#k do redis.call('del',k[i]) end return #k" 0 \
    | sed 's/^/==> cleared rate-limit keys: /' || true
fi

cd "$ROOT/apps/web"
E2E_BASE_URL="$WEB" npx playwright test "$@"
