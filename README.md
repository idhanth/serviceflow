# ServiceFlow

Operations platform for small service businesses - bookings, scheduling, job
assignment and progress tracking. The reference deployment is an auto detailing
shop; the domain model is business-type agnostic.

**Status: Phase 2 of 10 complete** (foundation and auth, plus customers,
employees, services and vehicles). See [Roadmap](#roadmap).

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

The sign-in page has a one-click button for each. The seed also creates the
organization's catalog and book of business: 6 services, 5 employees,
75 customers and 100 vehicles (PRD 49).

## Architecture

```
Next.js  ->  route handlers (/api/proxy)  ->  FastAPI  ->  service layer  ->  PostgreSQL
```

Two decisions worth knowing up front:

- **The session token never reaches client JavaScript.** It is stored in an
  httpOnly cookie and attached server-side by the proxy route handler, so an XSS
  bug cannot exfiltrate it.
- **Tenant scope is derived, never supplied.** `CurrentUser.organization_id`
  comes from a verified active membership. A caller can ask for an organization
  via `X-Organization-Id`, but a mismatch is refused, and a foreign organization
  is indistinguishable from a nonexistent one.

## Testing

```bash
cd apps/api && uv run pytest        # 71 tests
```

Covering health probes, the auth envelope, tenant isolation (including
cross-organization probing on every entity), per-organization role enforcement,
the customer-vs-customer boundary, employee deactivation revoking access, and
search, filtering and pagination.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation: repo, auth, organizations, roles, migrations | done |
| 2 | Customers, employees, services, vehicles | done |
| 3 | Booking workflow, assignment, job lifecycle | next |
| 4 | Availability, conflict detection, transaction safety, calendar | |
| 5 | Photos, notes, search, filtering, notifications | |
| 6 | Redis, Celery, email, realtime | |
| 7 | Idempotency, audit logs, rate limiting | |
| 8 | Integration, E2E, concurrency and load tests | |
| 9 | UI polish, responsive, dark mode | |
| 10 | CI/CD, production infrastructure, monitoring | |

Full specification: [docs/PRD.md](docs/PRD.md).
