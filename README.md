# ServiceFlow

Operations platform for small service businesses - bookings, scheduling, job
assignment and progress tracking. The reference deployment is an auto detailing
shop; the domain model is business-type agnostic.

**Status: Phase 3 of 10 complete** — the core workflow runs end to end: a
customer signs up, books a service, an admin assigns a technician and confirms,
and the employee starts and completes the job while the customer watches the
status change. See [Roadmap](#roadmap).

## Stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4, shadcn/ui (Base UI), TanStack Query |
| Backend | FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| Database | PostgreSQL 16 |
| Cache / queue | Redis (Celery lands in Phase 6) |
| Auth | Pluggable - local tokens by default, Clerk by configuration ([ADR 0001](docs/adr-0001-authentication-provider.md)) |

## Quick start

```bash
source scripts/env.sh
./scripts/services.sh start

cd apps/api
cp ../../.env.example ../../.env     # then set DATABASE_URL user + JWT_SECRET
uv sync --extra dev
uv run alembic upgrade head
uv run python -m serviceflow.db.seed
uv run uvicorn serviceflow.main:app --port 8000

# in a second shell
cd apps/web && npm install && npm run dev
```

Open http://localhost:3000.

With Docker available, `docker compose up` replaces `scripts/services.sh`.
Full details in [docs/local-development.md](docs/local-development.md).

## Demo accounts

Password for all three: `demo1234`

| Role | Email |
| --- | --- |
| Admin | `admin@serviceflow.demo` |
| Employee | `employee@serviceflow.demo` |
| Customer | `customer@serviceflow.demo` |

The sign-in page has a one-click button for each, and `/signup` creates a fresh
customer account if you'd rather walk the flow from the beginning.

The seed creates the organization's catalog and book of business: 6 services,
5 employees, 75 customers, 100 vehicles, 250 bookings and 199 jobs (180 of them
completed), per PRD 49. It is deterministic and idempotent — rerunning it
changes nothing.

## Architecture

```
Next.js  ->  route handlers (/api/proxy)  ->  FastAPI  ->  service layer  ->  PostgreSQL
```

Three decisions worth knowing up front:

- **The session token never reaches client JavaScript.** It is stored in an
  httpOnly cookie and attached server-side by the proxy route handler, so an XSS
  bug cannot exfiltrate it.
- **Tenant scope is derived, never supplied.** `CurrentUser.organization_id`
  comes from a verified active membership. A caller can ask for an organization
  via `X-Organization-Id`, but a mismatch is refused, and a foreign organization
  is indistinguishable from a nonexistent one.
- **A confirmed booking always has exactly one job.** The booking row is locked
  for the confirmation transaction, the state machine refuses a second confirm,
  and `jobs.booking_id` is unique — three independent guards, all tested
  ([ADR 0003](docs/adr-0003-phase3-booking-workflow.md)).

## Testing

```bash
cd apps/api && uv run pytest        # 119 tests
```

Covering health probes, the auth envelope, tenant isolation (including
cross-organization probing on every entity), per-organization role enforcement,
the customer-vs-customer boundary, employee deactivation revoking access, search,
filtering and pagination — and for the workflow: server-derived booking windows,
transactional job creation, repeated confirmation, rollback when confirmation
fails, employee job scoping, and every legal and illegal state transition.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation: repo, auth, organizations, roles, migrations | done |
| 2 | Customers, employees, services, vehicles | done |
| 3 | Booking workflow, assignment, job lifecycle | done |
| 4 | Availability, conflict detection, transaction safety, calendar | next |
| 5 | Photos, notes, search, filtering, notifications | |
| 6 | Redis, Celery, email, realtime | |
| 7 | Idempotency, audit logs, rate limiting | |
| 8 | Integration, E2E, concurrency and load tests | |
| 9 | UI polish, responsive, dark mode | |
| 10 | CI/CD, production infrastructure, monitoring | |

Full specification: [docs/PRD.md](docs/PRD.md).
