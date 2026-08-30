# Local development

## Why there is a non-Docker path

This project was built on a machine without Homebrew, Docker, or admin rights.
`scripts/services.sh` therefore runs PostgreSQL and Redis from user-local
conda-forge binaries. `docker-compose.yml` is the deployment-parity path and is
preferred wherever Docker is available; both bind the same ports (Postgres 5433,
Redis 6380), so `.env` works unchanged with either.

## Toolchain

| Tool | Version | Location |
| --- | --- | --- |
| Node | 24.20.0 | `~/.local/opt/node` (symlinked into `~/.local/bin`) |
| Python | 3.12 | managed by `uv` inside `apps/api/.venv` |
| PostgreSQL | 16.15 | micromamba env `serviceflow` |
| Redis | 8.10.1 | micromamba env `serviceflow` |
| MinIO | RELEASE.2025-09-07 | `~/.local/opt/minio` (S3-compatible object storage) |

`source scripts/env.sh` puts all of it on `PATH`.

## Running

```bash
source scripts/env.sh
./scripts/services.sh start          # Postgres + Redis + MinIO

cd apps/api
uv run alembic upgrade head          # migrations
uv run python -m serviceflow.db.seed # demo org + demo logins
uv run uvicorn serviceflow.main:app --port 8000 --reload

cd ../web
npm run dev                          # http://localhost:3000
```

`./scripts/services.sh stop` shuts the services down; `reset` wipes the data
directory and starts fresh.

## Object storage

MinIO stands in for AWS S3 locally. The bucket (`serviceflow-media`) is created
by the seed and stays private; photos are read through short-lived presigned
URLs. To inspect it:

```bash
mc alias set sfdev "http://127.0.0.1:$MINIO_PORT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc ls --recursive sfdev/serviceflow-media
```

For production on AWS, unset `S3_ENDPOINT_URL` and supply real IAM credentials;
nothing in the application changes. See
[ADR 0005](adr-0005-object-storage-and-notifications.md).

## Checks

```bash
cd apps/api && uv run ruff check . && uv run mypy src && uv run pytest
cd apps/web && npx eslint . && npx tsc --noEmit && npm run build
```
