# Architecture

ServiceFlow is a Next.js frontend, a FastAPI backend, PostgreSQL 16 as the system
of record, and Celery workers fed through Redis. This document explains how the
pieces fit and, more importantly, where each correctness guarantee actually
lives.

```
 Browser ──HTTPS──▶ Next.js server ─────────────▶ FastAPI ──▶ service layer ──▶ PostgreSQL 16
          cookie     /api/proxy, route handlers    /api/v1    (business rules)    constraints, RLS
          (httpOnly) token attached server-side                    │
                                                          outbox rows (same txn)
                                                                   │ after commit
                                                                   ▼
                                                     Redis ──▶ Celery worker ──▶ SMTP (Mailpit locally)
                                                       ▲             ▲
                                                 realtime pub/sub   Celery beat: reminders,
                                                  (SSE to browser)   outbox sweep, key expiry
```

## Repository layout

```
apps/api            FastAPI + SQLAlchemy 2 + Alembic (Python 3.12, uv)
  src/serviceflow/
    api/            routes: thin - resolve caller, check permission, call a service
    auth/           permissions table, principal, password hashing, token provider
    core/           settings, error envelope, pagination, logging, request context
    db/             models, tenancy (RLS context), session, demo seed
    schemas/        Pydantic request and response models
    services/       business logic: bookings, jobs, scheduling, members, dashboard...
    worker/         Celery app and tasks
  alembic/          migrations (the schema of record - tests build from these)
  tests/            pytest against real PostgreSQL, Redis, MinIO and Mailpit
apps/web            Next.js (App Router) + React 19 + TypeScript + Tailwind
  src/app/(app)/    authenticated screens
  src/components/   shell, data display, UI primitives
  src/lib/          API client, permissions, dates, formatting, types
  e2e/              Playwright suite
benchmarks/
  tenant_isolation/ invalid-write benchmark
  load/             dataset seeder, k6 scenario, runner
  results/          committed JSON results - the source of every number in the docs
docker/, docker-compose.yml   the full local stack
scripts/            benchmark and smoke-test runners
```

## Request path and authentication

1. The browser only ever talks to the Next.js server. Signing in posts to a Next.js
   route handler, which exchanges the credentials with the API and stores the
   returned JWT in an **httpOnly, SameSite=Lax cookie** (`Secure` in production).
   Browser JavaScript never sees the token, so an XSS bug cannot exfiltrate it.
2. Client components call `/api/proxy/...`; the proxy attaches the token and
   forwards server-side. Server components call the API directly the same way.
3. The API verifies the token (HS256, one-hour lifetime), loads the user, then
   loads their **active** memberships. The request's tenant is the membership's
   organization; an `X-Organization-Id` header can only *choose among* memberships
   the user already has. A header naming any other organization gets the same
   `403 TENANT_ACCESS_DENIED` whether that organization exists or not.
4. The resulting `CurrentUser` carries the organization, the roles held there, and
   the permissions those roles grant.

Passwords are hashed with Argon2id. Login and signup are rate limited per client
address (fail closed if Redis is down); authenticated endpoints per tenant and
user (fail open).

## Roles and permissions

Routes never check role names. `auth/permissions.py` maps each of the six tenant
roles to a set of permissions, and routes declare the permission they need:

```python
@router.post("/{job_id}/assign")
def assign_job(job_id: UUID, payload: JobReassign, current_user: JobsDispatcher, db: DbSession): ...
```

`JobsDispatcher` resolves to `require_permission(Permission.JOBS_DISPATCH)`, which
raises `403 INVALID_ROLE` for anyone else. Permissions answer *whether* a caller
may act; the service layer then narrows *what* they may act on:

| Permission holder | Narrowed to |
| --- | --- |
| `jobs:work` (technician) | jobs where `employee_id` is their own employee record |
| `bookings:own` (customer) | bookings where `customer_id` is their own customer record |
| `availability:own` | their own weekly hours and overrides |

A narrowed-out record reads as `404`, exactly like one that does not exist.

The platform administrator is a flag on the user, not a membership. It unlocks
`/platform/tenants` and nothing else; with no membership, every tenant route
refuses them. `tests/test_permission_matrix.py` exercises the whole matrix
through the API.

The frontend receives each membership's permission list from `/auth/me` and uses
it to shape navigation and hide actions. It never derives permissions from role
names itself, so it can only ever show less than the API allows.

## Tenant isolation

Three independent layers. Any one of them failing still leaves the other two.

**1. Application scoping.** Every service function takes the organization from
`CurrentUser` and filters by it. Records referenced in a request - the customer,
service and technician in a booking - are each loaded *through* that
organization, so another tenant's id is simply "not found".

**2. Composite foreign keys.** Tenant-owned tables carry `UNIQUE (organization_id,
id)`, and references between them are composite:

```sql
bookings (organization_id, customer_id) → customers (organization_id, id)
bookings (organization_id, service_id)  → services  (organization_id, id)
jobs     (organization_id, booking_id)  → bookings  (organization_id, id)
jobs     (organization_id, employee_id) → employees (organization_id, id)
employee_services, availability, notes, photos → likewise
```

A booking whose customer belongs to another tenant is not a validation failure
the application might forget - it cannot be stored.

**3. Row level security.** Every tenant table has RLS **enabled and forced** (so it
applies to the table owner, which is the application role) with one policy:

```sql
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
       OR current_setting('app.rls_bypass', true) = 'on')
WITH CHECK (same)
```

`db/tenancy.py` sets `app.organization_id` with `set_config(..., true)` -
*transaction-local*, so a pooled connection can never carry one request's tenant
into the next. The session remembers the tenant and an `after_begin` listener
re-applies it at the start of every transaction, including those that begin after
a service commits. A query that forgets its tenant filter therefore returns
nothing rather than everyone's rows, and an insert naming the wrong tenant fails
the policy's `WITH CHECK`.

The bypass is set only by `session_scope()` - used by Celery tasks, the seed and
migrations, which are cross-tenant by nature - and by the platform tenant counts.
This is a backstop against *application bugs*, not against someone who can
already run arbitrary SQL as the application role; parameterized queries are what
keep untrusted input from becoming SQL.

Row level security is only real if the application does not connect as a
superuser (superusers bypass every policy). Docker and CI create a dedicated
`serviceflow` role with `NOSUPERUSER NOBYPASSRLS`, and
`tests/test_row_level_security.py` asserts it.

## Booking safety

A booking and its job are written in one transaction. With a technician chosen:

1. every referenced record is loaded through the caller's tenant;
2. the scheduling policy checks the technician is active and qualified;
3. it checks the window against their working hours, resolved in the business's
   timezone (weekly hours, then date overrides);
4. it takes `pg_advisory_xact_lock(hash(employee_id))`, so concurrent requests for
   the same technician serialise instead of interleaving check-then-write;
5. it looks for overlapping live jobs, and refuses with a message naming the
   clash: *"Alex Morgan is already booked from 2:00 PM–3:00 PM."*;
6. the rows are inserted, and the notification and audit rows are staged in the
   same transaction.

Behind the application check sits the database:

```sql
ALTER TABLE jobs ADD CONSTRAINT jobs_no_overlapping_assignments
EXCLUDE USING gist (
    organization_id WITH =,
    employee_id WITH =,
    tstzrange(scheduled_start, scheduled_end) WITH &&
) WHERE (employee_id IS NOT NULL AND status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED'));
```

The range is half-open, so back-to-back appointments do not conflict. The advisory
lock makes a race produce a clean `409`; the constraint makes a race *impossible*
even for a code path that skipped the lock.

Duplicates are refused the same two ways: an application pre-check with a
friendly message, and a partial unique index on `(organization_id, customer_id,
service_id, requested_start) WHERE status IN ('PENDING','CONFIRMED')`. Retries of
the same request are handled separately by `Idempotency-Key`, claimed on a
unique constraint inside the booking's own transaction so a rollback takes the
key with it.

The job's state is also guarded by the database: `NEW` jobs cannot have a
technician, and `SCHEDULED`/`IN_PROGRESS`/`COMPLETED` jobs must. Status changes go
through one state machine. Every write path locks the booking and then the job,
in that order, so two requests touching one appointment from either end serialise
instead of deadlocking; lock queries use `populate_existing` so they can never
return a stale copy the session read earlier. The isolation benchmark found that
last bug: two simultaneous confirmations both succeeded before it was fixed.

## Background work

Business code never calls Celery or Redis. It writes notification rows (the
outbox) in its own transaction and stages the intent; an `after_commit` hook
queues the task. So:

- a rolled-back booking sends nothing;
- a broker outage right after commit loses nothing - the beat schedule's sweep
  re-queues any `PENDING` email row it finds;
- a stopped worker delays email but the web app keeps working, and `/health`
  stays green (it reports PostgreSQL and Redis, not Celery).

Workers claim a row with `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers never
send one message concurrently. Delivery is **at-least-once**: a worker that dies
after the SMTP server accepts a message but before marking it sent will send it
again. Reminders run every five minutes for appointments about 24 hours out, under
an advisory lock, and skip bookings already reminded.

Beat schedule: email sweep (60 s), appointment reminders (5 min), idempotency key
expiry (hourly).

## Data model

```
organizations ─┬─< organization_memberships >── users (global identity; is_platform_admin)
               ├─< customers ─< bookings >── services
               ├─< employees ─< employee_services >── services
               │       └─< employee_availability, availability_overrides
               ├─< bookings ── jobs (1:1) >── employees
               │                  └─< job_notes, job_photos
               ├─< notifications (outbox + in-app)
               ├─< audit_logs (append-only)
               └─< idempotency_records
```

Identity is global (one email, one user) while access is per tenant: a person can
be a customer of one business and a technician at another, and each membership
is scoped on its own. Emails are unique platform-wide; membership rows are unique
per `(organization, user, role)`.

## Pagination, indexes and the pool

- List endpoints take `page` and `page_size` (max 100) and return a total. Offset
  pagination is adequate at this scale because every list is tenant-filtered
  first: the largest tenant in the benchmark dataset holds 2,000 bookings. A
  platform-wide feed would need keyset pagination.
- Every sort ends with the primary key, so paging never repeats or skips rows.
- Composite indexes lead with `organization_id` for the tenant-filtered access
  paths the API actually uses: `(organization_id, requested_start)`,
  `(organization_id, status)`, `(organization_id, customer_id)` on bookings;
  `(organization_id, scheduled_start)`, `(employee_id, scheduled_start)` on jobs;
  `(organization_id, created_at)` on customers. See
  [benchmarks.md](benchmarks.md#query-plans) for the plans behind them.
- The SQLAlchemy pool is sized per process (`DATABASE_POOL_SIZE`,
  `DATABASE_MAX_OVERFLOW`), with `pool_pre_ping`, `pool_recycle` and a short
  `pool_timeout` (5 s). Exhaustion is reported as `503` with `Retry-After`, not as
  a `500`: congestion is capacity, not a defect.

## Errors

One envelope everywhere:

```json
{"error": {"code": "BOOKING_CONFLICT",
           "message": "Alex Morgan is already booked from 2:00 PM–3:00 PM. Choose another employee or time.",
           "request_id": "req_2f4c..."}}
```

Codes are stable (`UNAUTHORIZED`, `INVALID_ROLE`, `TENANT_ACCESS_DENIED`,
`NOT_FOUND`, `VALIDATION_FAILED`, `BOOKING_CONFLICT`, `INVALID_SCHEDULE`,
`INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`, `RATE_LIMITED`,
`DEPENDENCY_UNAVAILABLE`, `INTERNAL_ERROR`). Unhandled exceptions are logged with
the request id and the client receives a fixed sentence - never exception text,
SQL or a stack frame. Validation errors drop the rejected input, so a bad
password is never echoed back.

## Audit trail

`audit_logs` rows are staged in the transaction of the change they describe, and a
`BEFORE UPDATE OR DELETE` trigger rejects both statements, so the trail cannot be
rewritten by the application. Metadata is a summary chosen at the call site (never
note text, tokens or request bodies), with a filter that drops credential-shaped
keys as a backstop.

## Frontend

- One shell for every role: sidebar grouped by task, business identity, account
  menu, and navigation filtered by the permissions from `/auth/me`.
- One design system: colour, radius and a six-state status palette as tokens in
  `globals.css`; one type scale; tables (`DataPanel`, `Table`, `PrimaryCell`,
  `PanelFooter`) for records; stacked lists below the `md` breakpoint.
- Shared states: `TableSkeletonRows`/`CardSkeletons`, `EmptyState`, `ErrorState`
  with retry, toasts for success and failure, `ConfirmDialog` for destructive
  actions.
- TanStack Query for data, with one set of query keys so a booking change
  invalidates bookings, jobs, the schedule and the dashboard together.
- Dates and times are displayed - and booked - in the business's timezone, not
  the browser's.
