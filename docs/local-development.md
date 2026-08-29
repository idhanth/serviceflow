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

`source scripts/env.sh` puts all of it on `PATH`.

## Running

```bash
source scripts/env.sh
./scripts/services.sh start          # Postgres + Redis

cd apps/api
uv run alembic upgrade head          # migrations
uv run python -m serviceflow.db.seed # demo org + demo logins
uv run uvicorn serviceflow.main:app --port 8000 --reload

cd ../web
npm run dev                          # http://localhost:3000
```

`./scripts/services.sh stop` shuts the services down; `reset` wipes the data
directory and starts fresh.

## Checks

```bash
cd apps/api && uv run ruff check . && uv run mypy src && uv run pytest
cd apps/web && npx eslint . && npx tsc --noEmit && npm run build
```
