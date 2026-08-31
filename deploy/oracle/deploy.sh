#!/usr/bin/env bash
# Deploy a revision of ServiceFlow onto the VM.
#
#   SERVICEFLOW_REPO=<git-url> sudo -u serviceflow -H /opt/serviceflow/deploy.sh [git-ref]
#
# Releases are directories; `current` is a symlink. Migrations run once, before
# anything is restarted, and a failed migration aborts the deploy with the old
# release still serving.
set -euo pipefail

REF="${1:-main}"
REPO="${SERVICEFLOW_REPO:?set SERVICEFLOW_REPO to the git remote}"
APP_ROOT=/opt/serviceflow
RELEASES="$APP_ROOT/releases"
RELEASE="$RELEASES/$(date +%Y%m%d-%H%M%S)"

mkdir -p "$RELEASES"

echo "==> fetching $REF"
git clone --depth 1 --branch "$REF" "$REPO" "$RELEASE"

echo "==> building the virtualenv"
cd "$RELEASE/apps/api"
# --frozen: deploy exactly what the lockfile pins, never a resolved-at-deploy set.
# Absolute: this runs under sudo, where ~ is not reliably the app user's home.
/home/serviceflow/.local/bin/uv sync --frozen --no-dev

echo "==> migrations"
# Run once, here, from the new code but before it serves. Never at application
# startup: two API workers booting together would race the same migration.
# Readable because bootstrap.sh gives the file to root:serviceflow at 640.
set -a; . /etc/serviceflow/api.env; set +a
"$RELEASE/apps/api/.venv/bin/alembic" upgrade head

echo "==> switching"
ln -sfn "$RELEASE" "$APP_ROOT/current"

echo "==> restarting"
# Worker first so a new task shape is understood before the API can emit it;
# beat last so it schedules against a worker that is already up.
sudo systemctl restart serviceflow-worker
sudo systemctl restart serviceflow-api
sudo systemctl restart serviceflow-beat

echo "==> health"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    curl -fsS http://127.0.0.1:8000/ready || true
    echo; echo "deployed $(basename "$RELEASE")"
    # Keep the last five releases so a rollback is a symlink change.
    ls -1dt "$RELEASES"/*/ | tail -n +6 | xargs -r rm -rf
    exit 0
  fi
  sleep 2
done

echo "!! the API did not come up; check: journalctl -u serviceflow-api -n 50" >&2
exit 1
