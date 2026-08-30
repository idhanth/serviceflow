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
| MailPit | 1.31.0 | `~/.local/opt/mailpit` (SMTP capture, mailbox at :8025) |
| Playwright | 1.62.1 | `apps/web/node_modules`; browsers in `~/Library/Caches/ms-playwright` |
| k6 | 1.4.0 | `~/.local/opt/k6` (load testing) |

`source scripts/env.sh` puts all of it on `PATH`.

## Running

```bash
source scripts/env.sh
./scripts/services.sh start          # Postgres + Redis + MinIO + MailPit

cd apps/api
uv run alembic upgrade head          # migrations
uv run python -m serviceflow.db.seed # demo org + demo logins
uv run uvicorn serviceflow.main:app --port 8000 --reload

cd ../web
npm run dev                          # http://localhost:3000

# background jobs and the reminder scheduler, in another shell
cd ../.. && ./scripts/worker.sh
```

`./scripts/services.sh stop` shuts the services down; `reset` wipes the data
directory and starts fresh.

## Email

MailPit is a real SMTP server; the application delivers to it exactly as it would
to a production provider. Everything sent is readable at
<http://localhost:8025>, and the tests assert against its API rather than
stubbing the transport.

To use a real provider instead, set `EMAIL_PROVIDER=resend` and `RESEND_API_KEY`.
No application code changes.

## Background jobs

```bash
./scripts/worker.sh        # worker + beat
```

The beat schedule sweeps undelivered email every 60s, creates appointment
reminders every 5 minutes and purges expired idempotency records hourly. All
three are idempotent, so running several workers is safe. See
[ADR 0006](adr-0006-async-infrastructure-and-realtime.md).

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

## Idempotent booking requests

`POST /api/v1/bookings` accepts an optional `Idempotency-Key` header (8-200
characters of `A-Za-z0-9._:-`). To watch it work:

```bash
KEY="local-$(date +%s)"
for i in 1 2; do
  curl -s -o /dev/null -D - -X POST http://127.0.0.1:8000/api/v1/bookings \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: $KEY" \
    -d "{\"vehicle_id\":\"$VEH\",\"service_id\":\"$SVC\",\"requested_start\":\"$START\"}" \
    | grep -iE '^HTTP|idempotent-replay'
done
```

The first call returns `201`; the second returns `200` with
`Idempotent-Replay: true` and the identical body. Changing the payload while
reusing the key returns `409 IDEMPOTENCY_CONFLICT`. The browser does the same
thing: the wizard derives one key per version of the booking, so a double click
or a refresh mid-request cannot produce two appointments.

Records live in `idempotency_records` and are kept for 24 hours; the
`purge-expired-idempotency-keys` beat entry enforces that, or run it by hand:

```bash
cd apps/api && uv run python -c "
from serviceflow.db.session import session_scope
from serviceflow.services import idempotency
with session_scope() as db: print(idempotency.purge_expired(db), 'purged')"
```

## Activity and the audit trail

Every booking, job, employee, service, availability and photo/note mutation
writes a row to `audit_logs` in the same transaction as the change. Admins read
it at <http://localhost:3000/activity> or `GET /api/v1/activity`; customers and
employees get `403`.

The table is append-only, enforced by PostgreSQL rather than by convention:

```bash
psql -h 127.0.0.1 -p 5433 -d serviceflow \
  -c "UPDATE audit_logs SET action='JOB_STARTED' WHERE id=(SELECT id FROM audit_logs LIMIT 1);"
# ERROR: audit_logs is append-only: UPDATE is not permitted
```

That applies to `DELETE` too, which is why anything that legitimately needs to
clear the table (the test fixtures, a reseed) uses `TRUNCATE` - a statement-level
operation the row trigger does not see. The seed backfills ~1,000 historical
entries so the Activity page has something to show; see
[ADR 0007](adr-0007-idempotency-audit-and-limits.md) for what is and is not
recorded.

## Rate limits

Enabled by default in development, keyed in Redis under `sf:rl:*`:

| Limiter | Window | Identity | Without Redis |
| --- | --- | --- | --- |
| `signup` | 5 / hour | client address | fail **closed** |
| `login` | 10 / 15 min | client address | fail **closed** |
| `booking_create` | 20 / hour | org + user | fail open |
| `photo_presign` | 60 / 10 min | org + user | fail open |
| `search` | 120 / min | org + user | fail open |

Hitting one locally is easy - six signup attempts from one machine is enough -
and the response is `429` with `RATE_LIMITED`, a `Retry-After` header and a
matching `retry_after` in `details`. To get unstuck while developing:

```bash
redis-cli -p 6380 --scan --pattern 'sf:rl:*'          # what is counted
redis-cli -p 6380 eval "local k=redis.call('keys','sf:rl:*') \
  for i=1,#k do redis.call('del',k[i]) end return #k" 0   # clear it
```

Or set `RATE_LIMITING_ENABLED=false` to switch the whole layer off - which is
what the test suite does, except for `tests/test_rate_limiting.py`, which turns
it back on and runs against real Redis.

`TRUSTED_PROXY_COUNT` (default `0`) is how many proxies sit in front of the API.
At `0`, `X-Forwarded-For` is ignored entirely and the socket peer is used; set it
to the real hop count in a deployment, never higher, or a client can forge its
own identity and mint unlimited quota.

## Request ids and tracing

Every response carries `X-Request-Id`, generated per request or adopted from an
incoming header, and the same id appears in the error envelope and in every log
line for that request:

```bash
curl -s -D - http://127.0.0.1:8000/health | grep -i x-request-id

# follow one request across the API and the worker
grep req_5135b3777ede4d14 api.log worker.log
```

Logs are JSON on stdout, so `jq` is the comfortable way to read them:

```bash
uv run uvicorn serviceflow.main:app --port 8000 2>&1 | jq -c \
  'select(.logger=="serviceflow.access") | {method, path, status, user_id, request_id}'
```

Authenticated requests carry `user_id` and `organization_id`; unauthenticated
ones carry neither rather than logging blanks. Passwords, `Authorization`
headers, cookies, presigned S3 signatures and provider keys are never logged -
the formatter redacts credential-shaped keys as a backstop, and call sites do not
pass them in the first place. Correlation follows work into Celery, so the
request that caused an email and the task that sent it share one `request_id`.

## End-to-end tests

```bash
./scripts/services.sh start     # Postgres, Redis, MinIO, MailPit
./scripts/e2e.sh                # whole suite
./scripts/e2e.sh 02-customer    # one spec, or any Playwright filter
E2E_KEEP=1 ./scripts/e2e.sh     # leave the servers running afterwards
```

The script starts whatever is missing (API, Celery worker, a production build of
the web app), clears the `sf:rl:*` rate-limit counters, and stops only what it
started. First run needs the browser:

```bash
cd apps/web && npx playwright install chromium
```

Everything is real: uploads go to MinIO through a presigned POST, emails land in
MailPit, realtime arrives over SSE, and the rate limiters stay switched on - one
spec trips the sign-up limit on purpose. A run signs in three times (admin,
employee, the seeded demo customer) and signs up one fresh customer whose
surname carries the run id, so a run never acts on data an earlier one left.

Failures leave a trace: `npx playwright show-trace test-results/<name>/trace.zip`.

The suite adds bookings to the development database as it goes. To get back to
the exact demo state:

```bash
cd apps/api && uv run python -m serviceflow.db.seed   # tops up
# or, for a clean slate:
psql -h 127.0.0.1 -p $PGPORT -d postgres -c "DROP DATABASE serviceflow;" \
  -c "CREATE DATABASE serviceflow;"
uv run alembic upgrade head && uv run python -m serviceflow.db.seed
```

## Load tests

k6 lives at `~/.local/opt/k6/k6`. Runs go against an isolated database, never
the demo one:

```bash
./scripts/load.sh reset                  # build and seed serviceflow_load
./scripts/load.sh read-heavy 100 60s
./scripts/load.sh write-heavy 100 60s
./scripts/load.sh mixed 100 60s
./scripts/load.sh invariants             # what must still be true afterwards
./scripts/load.sh stop                   # shut the load API down
```

Summaries are written to `load/results/`. Pool sizing and worker count are part
of what a run measures:

```bash
LOAD_WORKERS=4 LOAD_POOL_SIZE=20 LOAD_MAX_OVERFLOW=4 ./scripts/load.sh read-heavy 500 60s
```

**This machine is the limit, not the application.** PostgreSQL here allows 100
connections in total, shared by the load API, the development API, the worker
and any psql session. Stop the development API and worker before a 500-user run,
or the numbers measure contention for connections. Measured results and what
they mean are in [ADR 0008](adr-0008-quality-strategy.md) and the README.

## Checks

```bash
cd apps/api && uv run ruff check . && uv run mypy src && uv run pytest
cd apps/web && npx eslint . && npx tsc --noEmit && npm run build
```
