#!/usr/bin/env bash
# Source this to put ServiceFlow's local toolchain on PATH.
#   source scripts/env.sh
export SERVICEFLOW_ROOT="${SERVICEFLOW_ROOT:-$HOME/serviceflow}"
export MAMBA_ROOT_PREFIX="$HOME/.local/opt/micromamba/root"
export SERVICEFLOW_SERVICES_BIN="$MAMBA_ROOT_PREFIX/envs/serviceflow/bin"
export PATH="$HOME/.local/bin:$HOME/.local/opt/node/bin:$HOME/.local/opt/minio/bin:$HOME/.local/opt/mailpit:$SERVICEFLOW_SERVICES_BIN:$PATH"

# Local dev service coordinates (see scripts/services.sh)
export PGHOST=127.0.0.1
export PGPORT=5433
export PGUSER="${PGUSER:-$(whoami)}"
export PGDATABASE=serviceflow
export REDIS_PORT=6380

# Local S3-compatible object storage (see scripts/services.sh). Development
# credentials only - production uses real AWS IAM keys from the environment.
export MINIO_PORT=9000
export MINIO_ROOT_USER=serviceflow
export MINIO_ROOT_PASSWORD=serviceflow-dev-secret

# Local mail capture (MailPit): a real SMTP server plus an HTTP API to inspect
# what was actually delivered. Production swaps in Resend/SendGrid/SES.
export MAILPIT_SMTP_PORT=1025
export MAILPIT_HTTP_PORT=8025
