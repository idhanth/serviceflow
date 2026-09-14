# Contributing

Thanks for looking. ServiceFlow is a portfolio project, but it is built the way a
team codebase would be, and changes are held to the same checks CI runs.

## Getting set up

The whole stack runs in Docker:

```bash
docker compose up --build
```

For day-to-day backend or frontend work you will usually want the services in
Docker and the code running natively, so it reloads:

```bash
docker compose up -d db redis mailpit minio minio-init
cd apps/api
cp ../../.env.example ../../.env
uv sync --extra dev
uv run alembic upgrade head
uv run python -m serviceflow.db.seed
uv run uvicorn serviceflow.main:app --reload --port 8000

# second terminal
cd apps/web && npm install && npm run dev

# third terminal: email, reminders and the outbox sweep
cd apps/api && uv run celery -A serviceflow.worker.celery_app worker --beat --loglevel=info
```

The compose file creates PostgreSQL's `serviceflow` role as a **non-superuser**.
Keep it that way: superusers bypass row level security, and
`tests/test_row_level_security.py` fails if the application connects as one.

## Before opening a pull request

```bash
cd apps/api
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run alembic check
uv run pytest

cd ../web
npx eslint src e2e && npx tsc --noEmit && npm run build

cd ../..
./scripts/bench-isolation.sh          # must report 0 unexpected successes
docker compose up --build -d && ./scripts/docker-smoke.sh
```

The tests run against real PostgreSQL 16, Redis, MinIO and Mailpit. Nothing that
the correctness guarantees depend on is mocked, and SQLite is never substituted:
the exclusion constraint, composite foreign keys and row level security only
exist in PostgreSQL.

## Rules the code relies on

- **Tenant scope comes from the caller, never from the request.** Take
  `organization_id` from `CurrentUser`. A new query on a tenant table still gets
  an explicit `organization_id` filter; row level security is the backstop, not
  the plan.
- **Ask for a permission, not a role.** Routes guard with `require_permission`,
  and the role-to-permission table lives only in `auth/permissions.py`.
- **Every booking has exactly one job.** Create them together; change job status
  only through `services/state_machine.py`.
- **Lock the booking, then the job.** Every write path takes locks in that order,
  and every `FOR UPDATE` query uses `populate_existing=True` so it cannot return a
  stale copy from the session.
- **Never call Celery or Redis from a business transaction.** Stage the intent with
  `services/outbox.py`; it is dispatched after commit.
- **Errors are `AppError` subclasses.** Never return exception text to a client.
- **Schema changes are Alembic migrations**, and `alembic check` must be clean.
- **Benchmarks report what they measure.** Never edit a file in
  `benchmarks/results/` by hand; rerun the script. Docs quote those files, and
  `tests/test_benchmark_claims.py` checks that they still agree.

## Commits

Small, focused commits with a message that explains *why*. Keep secrets, `.env`
files, database dumps and local data out of the repository.
