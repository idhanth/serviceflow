# ADR 0003 - Booking workflow and the phase 4 seam

Status: accepted
Date: 2026-08-30

Decisions made while building the booking and job workflow, plus the two phase 2
items that had to be resolved first.

## 1. Vehicles archive; services were already soft-deleted

ADR 0002 flagged that vehicles hard-deleted and that phase 3 would have to
revisit it. Bookings and jobs now reference vehicles, so `Vehicle.archived_at`
was added and `DELETE /vehicles/{id}` sets it instead of removing the row.

Archived vehicles disappear from listings, cannot be booked, and 404 on direct
read - but remain resolvable from the bookings that point at them. The
`bookings.vehicle_id` and `bookings.service_id` foreign keys use `ON DELETE
RESTRICT`, so the database refuses to lose history even if a future code path
tries. Archiving is idempotent, so a double-submitted request is safe.

## 2. Self-signup creates new accounts only

PRD 62 begins "customer signs up", so `POST /api/v1/auth/signup` creates a user,
a customer record and an active CUSTOMER membership, then returns a session.

It deliberately does **not** let someone claim a staff-created account that has
no password. Without email verification - which arrives with the email
infrastructure in phase 6 - anyone who knew a customer's address could take that
account over. Signup therefore refuses any address that already exists, with one
generic message for every failure so it cannot be used to test which addresses
are registered.

Consequence: the 74 seeded staff-created customers still cannot sign in. That is
unchanged from phase 2 and is resolved by an invitation flow in phase 6, not here.

**Not yet rate limited.** This is the only unauthenticated write endpoint in the
application. PRD 42 puts rate limiting in phase 7, and building half of it now
would be undone then - but until that lands, this endpoint can be used to create
unlimited accounts and must not be exposed publicly.

## 3. One job per booking, enforced three ways

"A confirmed booking must never exist without its job, and confirming twice must
never create two" is held by three independent mechanisms:

1. `confirm_booking` locks the booking row (`SELECT ... FOR UPDATE`) for the
   whole transaction, so concurrent confirms serialise.
2. The state machine refuses a second `PENDING -> CONFIRMED` transition.
3. `jobs.booking_id` carries a unique constraint, so a bug that got past both
   fails in the database rather than producing a duplicate.

The booking transition, the scheduling check and the job insert share one
transaction. A failure anywhere leaves the booking `PENDING` with no job, and the
booking stays confirmable once the cause is fixed. Both halves are tested.

Note that `FOR UPDATE` cannot span the eager-loaded outer joins these models
declare, so the locking queries force lazy loading. Phase 4 must keep that in
mind when adding row locks over employee jobs.

## 4. The scheduling seam

`services/scheduling.py` defines `SchedulingPolicy.check_assignment`, called from
inside the confirmation transaction with the live `Session`. Phase 3 ships
`QualificationPolicy`, which checks only what it can decide without an
availability model: the employee belongs to the organization, is active, and is
qualified for the service.

Phase 4 replaces the policy via `set_scheduling_policy` and adds availability,
overrides, overlap detection and locking there. Because the call already happens
inside the transaction and receives the full window plus an `exclude_job_id`,
none of the workflow, routes or tests need to change. Reschedule and reassign go
through the same seam, so they inherit phase 4's rules automatically.

A test asserts the seam is actually consulted during confirmation, so it cannot
be bypassed by a later refactor without failing.

## 5. Job lifecycle is exactly what the PRD specifies

`ASSIGNED -> IN_PROGRESS -> COMPLETED` and `ASSIGNED -> CANCELLED`. Nothing else.

In particular `IN_PROGRESS -> CANCELLED` is **not** allowed, because PRD 12 does
not list it. The consequence is deliberate and surfaced in the UI: once work has
started, its booking can no longer be cancelled or rescheduled, and the review
sheet says so rather than offering a button that would 409.

## 6. Employees have no booking access at all

PRD 6 gives employees jobs, not bookings. An employee calling any `/bookings`
route gets `403 FORBIDDEN`. An earlier revision let them fall through to a
customer lookup and returned a confusing 404 about a missing customer profile;
that is now an explicit role check.

## 7. Upcoming and past are exact complements

The customer's two tabs are computed from a single predicate and its negation, so
every booking appears in exactly one. A booking is "upcoming" only while it is
still ahead of its slot, still pending or confirmed, **and** has no completed or
cancelled job. Without the last clause a job finished ahead of its scheduled time
sat under "Upcoming" and never reached the customer's history. Found during
manual verification; a partition test now covers it.
