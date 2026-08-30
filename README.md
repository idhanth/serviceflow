# ServiceFlow

Operations platform for small service businesses - bookings, scheduling, job
assignment and progress tracking. The reference deployment is an auto detailing
shop; the domain model is business-type agnostic.

**Status: Phase 6 of 10 complete** — the product surface now sits on real
infrastructure: Celery workers deliver email off the request path, appointment
reminders run on a schedule, and Server-Sent Events push booking and job changes
to connected clients without polling. See [Roadmap](#roadmap).

## Stack

| Layer | Choice |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4, shadcn/ui (Base UI), TanStack Query |
| Backend | FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| Database | PostgreSQL 16 |
| Cache / queue | Redis — Celery broker and realtime pub/sub |
| Email | Provider-agnostic — MailPit over SMTP locally, Resend in production |
| Object storage | S3-compatible — MinIO locally, AWS S3 in production |
| Auth | Pluggable - local tokens by default, Clerk by configuration ([ADR 0001](docs/adr-0001-authentication-provider.md)) |

## Quick start

```bash
source scripts/env.sh
./scripts/services.sh start          # PostgreSQL, Redis, MinIO and MailPit

cd apps/api
cp ../../.env.example ../../.env     # then set DATABASE_URL user + JWT_SECRET
uv sync --extra dev
uv run alembic upgrade head
uv run python -m serviceflow.db.seed
uv run uvicorn serviceflow.main:app --port 8000

# in a second shell
cd apps/web && npm install && npm run dev

# in a third shell — background jobs and the reminder scheduler
./scripts/worker.sh
```

Captured email is readable at http://localhost:8025.

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
5 employees (each with their own weekly schedule and some time off), 75 customers,
100 vehicles, 250 bookings and 199 jobs (180 of them completed), per PRD 49. It is
deterministic and idempotent — rerunning it changes nothing — and it schedules
around working hours, so no seeded job overlaps another. It also adds 68 job
notes, 24 photos (uploaded to object storage for real) and a short notification
history for the demo customer.

## Architecture

```
Next.js  ->  route handlers (/api/proxy)  ->  FastAPI  ->  service layer  ->  PostgreSQL
                                                              |
                                                    notifications (outbox)
                                                        |            |
                                             Celery worker      Redis pub/sub
                                                  |                  |
                                            email provider    SSE -> browser
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
- **An employee can never hold two overlapping jobs.** A PostgreSQL exclusion
  constraint over `(employee_id, tstzrange(...))` makes it impossible whatever the
  application does, and a per-employee advisory lock turns the race into a clean
  409 instead of a constraint violation
  ([ADR 0004](docs/adr-0004-scheduling-concurrency.md)).
- **Emails are an outbox, not a side effect.** Notification rows are written
  inside the business transaction and dispatched only after it commits, so a
  rolled-back booking can never send mail — and a broker outage right after the
  commit is recovered by a periodic sweep rather than losing the message.
  Delivery is at-least-once, deliberately, and the duplicate window is documented
  ([ADR 0006](docs/adr-0006-async-infrastructure-and-realtime.md)).
- **Realtime events carry no record content.** An SSE envelope names what changed
  and who may know; the client refetches. A dropped event is therefore harmless,
  and a reconnecting client is correct again without replaying anything.
- **Photo bytes never pass through the API, and the bucket is never public.**
  The browser uploads to a presigned POST whose signed policy pins the content
  type and a 10 MB ceiling; the API then verifies the stored object before
  writing any metadata, so a `JobPhoto` row cannot describe a file that was not
  uploaded. Reads are short-lived presigned GETs
  ([ADR 0005](docs/adr-0005-object-storage-and-notifications.md)).

## Testing

```bash
cd apps/api && uv run pytest        # 393 tests
```

Infrastructure is exercised, not mocked: photo tests upload to MinIO for real,
email tests deliver over SMTP to MailPit and assert against its mailbox, realtime
tests publish through Redis, and one test runs an actual Celery worker as a
separate process. `./scripts/services.sh start` has to be running.

The schema under test is built by running the real migrations, not
`metadata.create_all` — the scheduling guarantee is a database constraint, so a
test database without it would prove nothing.

Coverage includes tenant isolation on every entity, per-organization roles, the
customer-vs-customer boundary, server-derived booking windows, transactional job
creation and rollback, every legal and illegal state transition, overlap
detection (adjacent, contained, partial), availability and override precedence,
timezone and daylight-saving boundaries, deterministic ranking — and the
concurrency suite below.

**Concurrency (PRD 52).** Real threads against real PostgreSQL, released from a
shared barrier so the race actually happens:

```bash
uv run pytest tests/test_concurrency.py    # 22 tests
```

Simultaneous overlapping assignments leave exactly one winner; simultaneous
adjacent ones all succeed; the same applies to concurrent reassignment and
reschedule.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation: repo, auth, organizations, roles, migrations | done |
| 2 | Customers, employees, services, vehicles | done |
| 3 | Booking workflow, assignment, job lifecycle | done |
| 4 | Availability, conflict detection, transaction safety, calendar | done |
| 5 | Photos, notes, search, filtering, notifications | done |
| 6 | Redis, Celery, email, realtime | done |
| 7 | Idempotency, audit logs, rate limiting | next |
| 8 | Integration, E2E, concurrency and load tests | |
| 9 | UI polish, responsive, dark mode | |
| 10 | CI/CD, production infrastructure, monitoring | |

Full specification: [docs/PRD.md](docs/PRD.md).
