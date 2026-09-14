# ServiceFlow — Product Requirements

ServiceFlow is a multi-tenant operations platform for service businesses that
manage customers, employees, bookings, schedules, field-service jobs, reminders
and internal workflows. This document is the specification the implementation
is built and checked against.

## 1. Goals

Independent businesses (tenants) manage, each fully isolated from the others:

1. customers
2. employees (technicians) and their working hours
3. services
4. bookings
5. schedules
6. service jobs
7. reminders and notifications
8. users, roles and permissions
9. administrative workflows (settings, members, audit trail)

The product must demonstrate backend correctness that holds under concurrency
and against mistakes in application code, not only a working UI.

## 2. Stack

| Area | Choice |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Backend | Python, FastAPI, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 |
| Background processing | Celery with Redis as broker |
| Local email | Mailpit |
| Infrastructure | Docker, Docker Compose |
| Testing | pytest against real PostgreSQL, Playwright, k6 |
| CI | GitHub Actions |

## 3. Roles

Seven roles. The backend is the source of truth for every permission; the UI
only hides what the API would refuse.

| Role | Scope | Can |
| --- | --- | --- |
| Platform Admin | the platform | list businesses and their size, create a business and its first owner. Holds no tenant membership, so reads no tenant's records |
| Business Owner | one tenant | everything in the tenant, including business settings and who has access |
| Business Manager | one tenant | staff, customers, services, bookings, jobs, schedules, audit trail |
| Dispatcher | one tenant | customers, bookings, assignments, schedules, availability |
| Technician | own work | their assigned jobs (start, complete, notes, photos) and their own availability |
| Customer | own records | book services, view and cancel their own bookings, view their service history, edit their profile |
| Analyst (read-only) | one tenant | read bookings, jobs, customers, employees, schedules and the audit trail; change nothing |

## 4. Multi-tenancy

- Every business is a tenant (an *organization*). `organization_id` is the tenant
  key on every tenant-owned table: customers, employees, services, qualifications,
  availability, bookings, jobs, notes, photos, notifications, audit entries,
  idempotency records.
- A user from Tenant A must never read, change, reference or trigger work on
  Tenant B's records.
- Isolation is enforced in three layers: application scoping from the verified
  caller, composite foreign keys that make mixed-tenant rows unrepresentable, and
  PostgreSQL row level security as a backstop against a missing filter.
- A foreign record's id must read exactly like a nonexistent one (no enumeration).

## 5. Authentication

- Email and password, Argon2id hashing.
- Short-lived signed JWTs held in an httpOnly cookie by the Next.js server; the
  token never reaches browser JavaScript.
- Secrets from environment variables; only `.env.example` is committed.
- Login and signup are rate limited per client address.

## 6. Core entities

**Customers**: name, email, phone, service address, internal notes, archived flag.
Create, view, update, archive, search, list with pagination, booking and job history.

**Employees**: profile, job title, qualified services, weekly working hours, date
overrides (time off / special hours), active flag, schedule, assigned jobs.

**Services**: name, description, duration, price, active flag. Retired rather than
deleted, so history keeps its meaning.

**Bookings**: customer, service, requested start; the end is always derived from
the service duration on the server. Statuses: `PENDING`, `CONFIRMED`,
`REJECTED`, `CANCELLED`.

**Jobs**: one per booking, created with it. Tenant, booking, technician, scheduled
window, status, notes, photos, start and completion timestamps. Statuses:
`NEW → SCHEDULED → IN_PROGRESS → COMPLETED`, or `CANCELLED` before work starts.

## 7. Booking flow

```
select customer (staff) → select service → select date/time → select technician (optional)
→ validate tenant membership of every record → validate role permission
→ validate working hours → prevent overlap and duplicates
→ create booking and job in one transaction
→ queue confirmation email (after commit)
```

- With a technician: booking `CONFIRMED`, job `SCHEDULED`.
- Without: booking `PENDING`, job `NEW`, waiting on the jobs board for assignment.
- A conflict is explained in words, e.g. *"Alex Morgan is already booked from
  2:00 PM–3:00 PM. Choose another employee or time."* Raw database errors are
  never shown.

## 8. Booking safety

- **Overlap:** a technician can never hold two live jobs whose time ranges overlap.
  Enforced by a PostgreSQL exclusion constraint over
  `(organization_id, employee_id, tstzrange(scheduled_start, scheduled_end))`,
  with a per-technician advisory lock so concurrent requests serialise into a
  clean `409` rather than a constraint error. Adjacent slots do not conflict.
- **Duplicates:** an open booking for the same customer, service and start cannot
  be stored twice (partial unique index), and an `Idempotency-Key` makes a retried
  request replay the original instead of creating a second one.
- **Cross-tenant references** are refused by composite foreign keys.

## 9. Scheduling

Day and week views with technicians as rows, their working hours shaded, jobs
placed by status, and unassigned work in its own row. Filter by technician and
status. Technicians see only their own lane. Times are shown in the business's
timezone.

## 10. Background work

Celery with Redis:

- booking confirmation, rejection, cancellation and completion emails;
- appointment reminders about 24 hours ahead (periodic, idempotent);
- a sweep that re-queues any email the broker missed;
- expiry of idempotency keys.

The booking transaction never depends on email. Notification rows are written in
the business transaction (an outbox) and dispatched after commit; a worker outage
delays mail but cannot corrupt or lose it. Delivery is at-least-once.

## 11. API

REST under `/api/v1`, including: `POST /auth/login`, `GET /me`, `GET/POST
/customers`, `GET/PATCH/DELETE /customers/{id}`, `GET/POST /employees`, `GET/POST
/services`, `GET/POST /bookings`, `GET/PATCH /bookings/{id}`, `GET /jobs`,
`GET/PATCH /jobs/{id}`, `GET /schedule`, `GET /dashboard`, `GET/POST/PATCH
/members`, `GET/POST /platform/tenants`, `GET /health`.

- Pagination is bounded (`page`, `page_size ≤ 100`) with a total count.
- Errors use one envelope with a stable code: `UNAUTHORIZED`, `INVALID_ROLE`,
  `TENANT_ACCESS_DENIED`, `NOT_FOUND`, `VALIDATION_FAILED`, `BOOKING_CONFLICT`,
  `INVALID_SCHEDULE`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`,
  `RATE_LIMITED`, `DEPENDENCY_UNAVAILABLE`.
- `GET /health` reports PostgreSQL and Redis and never fails because Celery is down.

## 12. Audit trail

Append-only (a trigger rejects UPDATE and DELETE). Records booking created,
confirmed, cancelled and rescheduled; jobs assigned, started, completed and
cancelled; customers and employees added or changed; members invited, role
changes and suspensions; settings changes; tenant creation.

## 13. Frontend

A consistent application shell (sidebar, header, business identity, account
menu) with role-aware navigation; a shared component system; loading, empty,
error and success states on every screen; confirmations for destructive
actions; responsive layouts down to phones; semantic, keyboard-accessible markup.

Screens: sign-in with demo role quick access, dashboard, schedule, bookings list
and detail, booking wizard, jobs list and detail, customers list and detail,
employees, services, availability, activity, settings and members, customer
profile, platform businesses.

## 14. Demo data

Realistic, immediately convincing data for Northside Home Services (plus two other
businesses so isolation can be tried): named customers such as Sarah Mitchell,
James Carter and Emily Rodriguez; technicians such as Alex Morgan (HVAC), Chris Lee
(plumbing) and Jordan Patel (field); services such as HVAC Inspection, Emergency
Plumbing Repair and Preventive Maintenance; history, today's schedule and
upcoming work. Demo accounts use the password `demo1234` and exist only in the
local demo database.

## 15. Verification

- Unit and integration tests against real PostgreSQL, including tenant isolation,
  row level security, database constraints, permissions, state transitions and
  concurrency.
- A **tenant isolation benchmark** that attempts thousands of invalid writes
  (duplicates, overlaps, concurrent races, cross-tenant references and access,
  unauthorized roles, raw SQL bypasses) and reports attempted, blocked and
  unexpected successes per category. Success requires zero unexpected successes.
- A **load test** with a weighted, authenticated endpoint mix against a
  multi-tenant dataset, reporting throughput, p50/p95/p99 latency, error rate
  and database connection behaviour, with hardware and configuration recorded.
- A **Docker smoke test** proving a fresh stack works end to end.
- Results are committed as JSON and the documentation quotes only those files.
