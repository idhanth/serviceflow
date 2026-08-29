# ServiceFlow - Product Requirements

A production-style operations platform for small service businesses (auto
detailing, cleaning, landscaping, photography, tutoring, repair, home services).
The demo business is an **auto detailing shop**; the architecture stays generic
enough that the business type could change without a rewrite.

## 1. Primary goal

Demonstrate professional frontend engineering, backend architecture, relational
database design, authentication, role-based authorization, business workflows,
scheduling logic, concurrency handling, asynchronous processing, file storage,
realtime updates, analytics, testing, CI/CD, deployment, logging, monitoring and
polished UX. It must feel like a real SaaS product, not a student CRUD project.

## 2. Positioning

Manage customers, employees, services, vehicles/assets, bookings, scheduling, job
assignments, job progress, before/after photos, notes, notifications, analytics
and audit history.

Core workflow:

```
Customer requests service -> Admin reviews booking -> Admin assigns employee
-> System checks scheduling conflicts -> Booking confirmed -> Employee performs job
-> Employee updates progress -> Employee uploads photos/notes -> Job completed
-> Customer notified -> Dashboard updates
```

This workflow must work flawlessly end to end.

## 3. Tech stack

**Frontend:** Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, TanStack
Query, React Hook Form, Zod, Recharts, Lucide icons. Framer Motion optional;
animation used sparingly.

**Backend:** FastAPI, Python, SQLAlchemy 2.x, Pydantic, Alembic.
**Database:** PostgreSQL. **Background jobs:** Redis + Celery.
**Auth:** Clerk preferred (or Supabase Auth); do not hand-build password
infrastructure unless necessary; authorization still enforced in FastAPI.
**Storage:** S3 or S3-compatible, presigned uploads.
**Email:** Resend, SendGrid or AWS SES.
**Realtime:** SSE preferred; WebSockets only if bidirectional is truly needed.
**Testing:** pytest, Playwright. **DevOps:** Docker, Docker Compose, GitHub Actions.

## 4. Architecture

```
Frontend -> REST API -> Service layer -> Repository/DB -> PostgreSQL
FastAPI -> Redis -> Celery worker -> email / scheduled tasks / processing
Frontend -> presigned URL request -> S3 -> metadata in PostgreSQL
```

Core business logic must not live in API route handlers.

## 5. Multi-tenancy

Each business is an Organization owning its own customers, employees, services,
vehicles, bookings, jobs, photos, notifications and audit logs. Every
business-owned record carries `organization_id`. A user in Organization A must
never read or mutate Organization B's data. This must be tested.

## 6. Roles

`CUSTOMER`, `EMPLOYEE`, `ADMIN` - held at the organization membership level, not
globally. Authorization enforced server-side.

- **Customer:** own profile, own vehicles, available services, request/view/cancel
  own bookings, completed jobs, customer-visible photos and notes, notifications.
  Never: admin data, other customers, employee assignment, service edits, internal notes.
- **Employee:** assigned jobs, schedule, job status updates, internal and
  customer-visible notes, photo upload, own availability. Never: unrelated jobs,
  role changes, business settings, admin-only financial data.
- **Admin:** customers, employees, services, bookings, assignment, schedules, all
  jobs, reschedule/cancel, analytics, audit logs, organization settings.

## 7. Data model

**Organization:** id, name, slug, email, phone, timezone, address, logo_url, created_at, updated_at
**User:** id, auth_provider_id, first_name, last_name, email, phone, avatar_url, created_at, updated_at
**OrganizationMembership:** id, organization_id, user_id, role, status, created_at
**Customer:** id, organization_id, user_id, notes, created_at, updated_at
**Employee:** id, organization_id, user_id, job_title, active, created_at, updated_at
**Service:** id, organization_id, name, description, base_price, duration_minutes, active, image_url, created_at, updated_at
**EmployeeService:** employee_id, service_id
**Vehicle:** id, organization_id, customer_id, year, make, model, color, license_plate, notes, created_at, updated_at
**Booking:** id, organization_id, customer_id, vehicle_id, service_id, requested_start, requested_end, status, customer_notes, admin_notes, created_at, updated_at - status `PENDING | CONFIRMED | REJECTED | CANCELLED`
**Job:** id, organization_id, booking_id, employee_id, scheduled_start, scheduled_end, status, started_at, completed_at, internal_notes, created_at, updated_at - status `ASSIGNED | IN_PROGRESS | COMPLETED | CANCELLED`
**JobPhoto:** id, organization_id, job_id, uploaded_by, photo_type, storage_key, public_url, mime_type, file_size, created_at - type `BEFORE | AFTER | OTHER`
**JobNote:** id, organization_id, job_id, author_id, content, visibility, created_at, updated_at - visibility `INTERNAL | CUSTOMER_VISIBLE`
**EmployeeAvailability:** id, organization_id, employee_id, day_of_week, start_time, end_time
**AvailabilityOverride:** id, organization_id, employee_id, date, available, start_time, end_time, reason
**Notification:** id, organization_id, user_id, type, channel, status, subject, body, created_at, sent_at, failed_at
**AuditLog:** id, organization_id, actor_user_id, action, resource_type, resource_id, metadata, created_at - immutable

## 8. Booking workflow

Customer selects service, vehicle, date, time and optional notes. End time is
computed from service duration (e.g. Full Detail, 10:00 AM, 150 min -> 12:30 PM).
Booking starts `PENDING`. Admin may confirm, reject, reschedule or cancel.

On confirmation: an employee must be selected, must support the service, must be
available, must not have an overlapping job; a Job record is created; a
confirmation notification is queued; an audit event is recorded; a realtime event
is sent.

## 9. Scheduling engine

Overlap condition: `new_start < existing_end AND new_end > existing_start`.

Frontend checks are not authoritative - the backend validates, and the database
layer protects against race conditions. Two simultaneous requests must not both
succeed in claiming the same slot. Use transactions, locking, constraints and
appropriate isolation. Concurrency tests proving this are mandatory.

## 10. Employee availability

Weekly availability per employee, plus date-specific overrides (vacation,
holiday, sick day, special availability). Unavailable employees are disabled or
deprioritized in the assignment UI.

## 11. Employee recommendation

Deterministic ranking when assigning: service capability, availability,
scheduling conflicts, jobs already that day, total scheduled hours. Not AI.

## 12. Job lifecycle

`ASSIGNED -> IN_PROGRESS -> COMPLETED`, plus `ASSIGNED -> CANCELLED`.
`COMPLETED -> IN_PROGRESS` is invalid. Invalid transitions return HTTP 409 with a
structured error. Use a centralized state transition service.

## 13. Background jobs

Celery + Redis handle booking confirmation, cancellation, reminder and completion
emails, retry logic and periodic jobs. API requests never wait on email
providers: commit, queue, respond.

## 14. Idempotency

Booking creation accepts an `Idempotency-Key`. Store organization, user, key,
response and expiration. Same key + same payload returns the original result;
same key + different payload returns a conflict.

## 15. Photo uploads

JPEG/PNG/WebP, max 10 MB each, max 12 per job, via presigned S3 uploads. UI needs
drag-and-drop, upload progress, thumbnails, retry, delete before completion and a
photo-type selector. No arbitrary executable files.

## 16. Notifications

Channels `EMAIL`, `IN_APP`. Events: BOOKING_CREATED, BOOKING_CONFIRMED,
BOOKING_REJECTED, BOOKING_RESCHEDULED, BOOKING_CANCELLED, APPOINTMENT_REMINDER,
JOB_STARTED, JOB_COMPLETED. Customer notification center shows unread state.

## 17. Realtime

SSE (or WebSockets) for booking updates, job status changes, new notifications
and dashboard refresh. If the connection fails, fall back to query refetching.

## 18-20. Dashboards

**Admin:** greeting header with search/notifications/avatar; KPI cards (today's
jobs, pending bookings, in progress, completed this week, estimated revenue) with
metric, context, subtle icon and optional period comparison; today's schedule as
a timeline; booking requests table; revenue/jobs chart; recent activity feed.
Must not look cluttered.

**Employee:** greeting with today's counts; a visually dominant "next job" card;
today's schedule, job status, customer, vehicle, service, notes, photo upload,
start/complete actions.

**Customer:** upcoming appointment hero card, booking status, previous jobs,
vehicles, notifications, quick booking button.

## 21-22. Design direction and system

Modern B2B SaaS: clean, premium, calm, professional, spacious, information-dense
without clutter, polished light and dark modes. Not gaming, crypto, neon or
gradient-heavy. Soft borders, subtle shadows, rounded cards, strong spacing
hierarchy, professional typography, restrained accent color, clear status colors,
tasteful animation.

Radius: cards 12-16px, buttons/inputs 8-10px, badges full or 6-8px. 8px spacing
system. Inter or Geist; do not mix many fonts. Hierarchy: page title, section
title, card title, body, metadata, caption.

## 23. Navigation

Desktop sidebar: Dashboard, Bookings, Jobs, Calendar, Customers, Employees,
Services, Analytics, Activity, Settings; organization switcher and user account
at the bottom. Mobile: compact top nav, slide-out menu, responsive cards/tables,
no horizontal overflow.

## 24-31. UI requirements

**Tables:** search, filtering, sorting, pagination, loading skeleton, empty
state, row actions, sticky header where useful, responsive. Use drawers or detail
pages instead of 50 columns.

**Status badges:** consistent styles for booking and job statuses; never rely on
color alone.

**Forms:** visible label, validation, loading/disabled/success/error states,
correct input types, errors beside the relevant field, "Save Changes" ->
"Saving...", no duplicate submissions.

**Loading:** deliberate skeletons for dashboard cards, tables, detail pages, job
cards and calendars. Avoid giant generic spinners.

**Empty states:** explain what happened and what to do next, with a CTA.

**Errors:** never raw backend errors. "We couldn't assign this employee because
the selected time conflicts with another job", not `KeyError employee_id`.
Include retry where appropriate.

**Toasts:** tasteful, for confirmations and failures; not excessive.

**Confirmation dialogs:** required for cancel booking, delete service, deactivate
employee, remove photo - and must explain consequences.

## 32-35. Search, calendar, analytics, audit

Global admin search across customers, vehicles, bookings, jobs and employees;
Cmd/Ctrl+K command palette optional but valuable.

Calendar: day and week views, filters by employee/status/service, events showing
time, customer, service, employee and status, click to open a details drawer.
Desktop-first; mobile uses an agenda view.

Analytics: revenue trend, jobs completed, bookings by service, jobs per employee,
average job duration, cancellation rate. Simple charts, not a BI system.

Audit log: actor, action, resource, timestamp, metadata, filterable by actor,
action, date and resource.

## 36-38. API

Prefix `/api/v1`. REST semantics throughout.

```
POST/GET   /bookings          GET/PATCH /bookings/{id}
POST       /bookings/{id}/confirm | reject | cancel
GET        /jobs              GET /jobs/{id}
POST       /jobs/{id}/assign | start | complete
GET        /customers  /customers/{id}
GET        /employees  /employees/{id}
GET/POST   /services
GET        /dashboard         GET /audit-logs
```

Collection: `{"data": [], "meta": {"page","page_size","total","pages"}}`.
Single: `{"data": {}}`.
Error: `{"error": {"code","message","request_id"}}`.

Error codes: VALIDATION_FAILED, UNAUTHORIZED, FORBIDDEN, NOT_FOUND,
SCHEDULE_CONFLICT, INVALID_STATE_TRANSITION, IDEMPOTENCY_CONFLICT, RATE_LIMITED,
UPLOAD_FAILED, DEPENDENCY_UNAVAILABLE, INTERNAL_ERROR.

## 39-40. Database and time

Foreign keys, unique constraints, check constraints, indexes and migrations.
Index organization_id, customer_id, employee_id, status, scheduled_start,
created_at; composites on (organization_id, status), (employee_id,
scheduled_start), (organization_id, customer_id).

Store all timestamps in UTC; each organization has a timezone; display in it.
No naive datetimes.

## 41-44. Security, rate limiting, logging, monitoring

Server-side authorization, tenant isolation, secure authentication, CSRF
protection where relevant, input validation, rate limiting, safe file upload
validation, secrets in environment variables and never committed, no sensitive
data in logs, proper CORS, ORM parameterization, security headers, short-lived
presigned URLs.

Rate limit login, registration, password reset, booking creation, upload presign
and search abuse; return 429 with a useful message.

Structured JSON logs with timestamp, request_id, method, path, status,
duration_ms, user_id, organization_id. Never log passwords, tokens or secrets.

`GET /health` (process alive) and `GET /ready` (database and Redis reachable).
Track request count, error rate, p95 latency, Celery failures, queue length and
schedule conflicts.

## 45-48. Performance, accessibility, responsive, dark mode

p95 under 300 ms locally for normal API requests; dashboard shows meaningful
content quickly. Avoid N+1 queries, excessive queries, large bundles and
unnecessary client rendering. Paginate; use eager loading intentionally.

Reasonable WCAG compliance: keyboard navigation, labels, focus states, semantic
HTML, contrast, accessible dialogs, aria labels. Prefer shadcn's accessible
primitives over custom controls.

Must work at 1440, 1024, 768 and 390 px with no broken layouts and no horizontal
scrolling from tables. Light, dark and system themes, all deliberate.

## 49-50. Demo data and accounts

Seed 1 organization, 1 admin, 5 employees, 75 customers, 6 services, 100
vehicles, 250 bookings and 180 completed jobs. Services: Exterior Detail,
Interior Detail, Full Detail, Paint Correction, Ceramic Coating, Express Wash.
Realistic names and dates.

Provide admin, employee and customer demo logins, clearly documented in the
README, so recruiters can explore immediately.

## 51-55. Testing and CI

**Unit:** booking duration, overlap detection, state transitions, authorization
helpers, recommendation scoring, validation, timezone conversion.

**Integration:** authentication, tenant isolation, booking APIs, employee
assignment, conflict prevention, notification task creation, photo metadata,
database transactions.

**E2E (Playwright):** customer login -> book service -> admin login -> approve ->
assign -> employee login -> start job -> upload photos -> complete -> customer
sees completion. Must pass automatically.

**Concurrency (mandatory):** simultaneous requests assigning the same employee to
overlapping jobs - exactly one succeeds, the rest fail cleanly.

**Failure:** Redis down, email provider down, S3 upload failure, transaction
failure, realtime drop, duplicate request, lost authorization, employee
deactivated, service deactivated. Fail gracefully.

**Load (k6 or Locust):** 100 then 500 concurrent users; measure throughput,
latency and error rate. Do not claim unmeasured numbers.

**CI:** install -> lint -> typecheck -> backend tests -> frontend tests ->
integration tests -> build on every PR. Broken tests block deployment.

## 56-59. Quality rules

No TODO/FIXME/`pass`, temporary mocks, fake API calls, hardcoded IDs, disabled
tests, ignored type errors or console errors in finished production paths. No
silent exception swallowing. Avoid giant files; keep functions and components
scoped.

Every page needs loading, error, empty and success states. Every mutation must
prevent duplicate submission, show progress, handle errors, update the UI and
invalidate the right queries. No page should need a manual refresh.

Transitions 150-250 ms on dialogs, dropdowns, sidebar, accordions, status changes
and cards. No giant page transitions, bouncing, excessive motion or 3D.

Before declaring UI complete verify: consistent spacing, radii, button heights
and typography; no misaligned icons, random colors, overflowing text, clipped
menus or broken mobile layouts; polished skeletons and useful empty states.

## 60. Build order

1. Foundation: repo, frontend, backend, PostgreSQL, Docker, auth, organizations, roles, migrations
2. Core entities: customers, employees, services, vehicles
3. Core workflow: booking, approval, assignment, job creation, job lifecycle
4. Scheduling: availability, conflict detection, transaction safety, calendar
5. Product features: photos, notes, search, filtering, pagination, notifications
6. Infrastructure: Redis, Celery, email, realtime
7. Advanced: idempotency, audit logs, rate limiting, structured errors, logging
8. Quality: unit, integration, E2E, concurrency and load tests
9. UI polish: responsive, dark mode, animation, dashboard, state coverage
10. Deployment: CI/CD, production database, Redis, storage, email, monitoring, demo accounts

## 61. Implementation instructions

- Build incrementally; never attempt the whole project in one pass.
- After each major feature run typechecks, linting, tests and the build, and
  resolve failures before continuing.
- Do not leave knowingly broken code for later phases.
- Do not invent libraries or APIs; verify packages and interfaces before use.
- Do not silently change the architecture without documenting why.
- Favor simple, maintainable implementations over unnecessary abstraction.
- Business logic belongs in backend service modules, not routes or components.
- All authorization is enforced on the backend.
- Every query touching organization-owned data enforces tenant isolation.
- Never trust frontend-supplied IDs without checking ownership and authorization.
- Every major screen has loading, empty, error and success states.
- No feature is complete until its tests pass.

## 62. Definition of done

This exact flow works on the deployed application:

```
Customer signs up -> adds vehicle -> selects Full Detail -> requests Saturday 10 AM
-> Admin sees pending booking -> opens it -> system shows available employees
-> Admin assigns employee -> system validates schedule -> booking confirmed
-> customer notified -> employee sees assignment -> employee starts job
-> admin sees realtime status update -> employee uploads before photos
-> adds a note -> completes job -> uploads after photos
-> customer receives completion notification -> customer sees finished job
-> admin dashboard updates -> audit log contains the entire workflow
```

Plus: no console errors, no failed network calls in normal flow, no broken links,
no unauthorized data exposure, no duplicate bookings from repeated submission, no
double-booked employees, no broken responsive layouts, all critical tests pass,
production build passes.

## 63-64. Scope

Do not add features to make the app larger. Avoid initially: AI chatbot, payroll,
accounting, GPS, route optimization, native mobile apps, social feeds, crypto,
video chat, complex inventory, machine learning.

Stretch, only once everything above is stable: Stripe (deposit, payment, refund,
webhooks), customer reviews, recurring bookings, PWA installability, organization
branding (logo, brand name, accent color).

## 65-66. Bar

The product should look like something that could plausibly charge $49-149/month
to a real small business. The reaction should be "this looks like an actual SaaS
dashboard", not "this is a nice school project". Polish comes from consistency,
responsiveness, useful workflows, good spacing, clean typography and fast
interactions - not flashy effects.

Resume-level depth by completion: React/Next.js, TypeScript, FastAPI,
PostgreSQL, REST APIs, RBAC, multi-tenancy, transactions, concurrency, Redis,
Celery, S3, realtime systems, background processing, idempotency, testing,
Docker, CI/CD, monitoring, performance. No further technologies needed.

## 67. Standing instruction

Treat this as a production-style portfolio project rather than a prototype.
Prioritize correctness, usability, maintainability and visual polish. Do not rush
features to check boxes. Each critical workflow must be fully implemented,
validated, tested and polished before moving on. Use realistic seeded data and
ensure the deployed application can be explored immediately with demo accounts.
Keep the UI visually consistent and premium throughout. Before declaring the
project complete, run the full test suite, production builds, linting, type
checking, critical E2E flows, responsive checks and concurrency tests, and
resolve all known errors.
