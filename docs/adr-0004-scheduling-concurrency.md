# ADR 0004 - Scheduling semantics and concurrency protection

Status: accepted
Date: 2026-08-30

How phase 4 decides whether an employee can take a piece of work, and how that
decision is made safe when two people ask at the same instant.

## 1. Two mechanisms, not one

The invariant is: **one employee never holds two overlapping non-cancelled jobs.**

Two independent things enforce it.

**A PostgreSQL exclusion constraint** is the guarantee:

```sql
ALTER TABLE jobs ADD CONSTRAINT jobs_no_overlapping_assignments
EXCLUDE USING gist (
    employee_id WITH =,
    tstzrange(scheduled_start, scheduled_end) WITH &&
) WHERE (status <> 'CANCELLED'::job_status);
```

It holds regardless of application code. A future endpoint that forgets to
consult the scheduling policy cannot write an overlap; the insert fails. It also
gets adjacency right for free: `tstzrange` is half-open, so `[10:00, 12:00)` and
`[12:00, 14:00)` do not intersect, which is exactly PRD 9's rule
(`new_start < existing_end AND new_end > existing_start`).

**A transaction-scoped advisory lock** is the user experience:

```sql
SELECT pg_advisory_xact_lock(hashtext(:employee_id))
```

taken inside `AvailabilityPolicy.check_assignment` before the overlap query. It
serialises concurrent assignment attempts for one employee, so the check-then-write
sequence cannot interleave, and the loser gets a considered
`409 SCHEDULE_CONFLICT` naming the clashing job instead of a raw constraint
violation.

### Why both

The constraint alone is correct but produces a poor error: by the time it fires
the transaction is already doomed, and the message is a Postgres string, not
something a person can act on. Distinguishing it from the unrelated
`one_job_per_booking` unique constraint would also mean parsing error text on
every write.

The lock alone is not correct: it is advisory, so it only protects code paths
that remember to take it.

Together, the lock makes the common path give a good answer and the constraint
makes every path safe. This mirrors the phase 3 treatment of "one job per
booking" - lock, then state machine, then unique constraint.

### Rejected alternatives

- **`SERIALIZABLE` isolation.** Correct, but pushes serialisation failures onto
  every caller, needs a retry loop around unrelated writes, and would have to be
  reasoned about for the whole application rather than one operation.
- **`SELECT ... FOR UPDATE` over the employee's jobs.** The conflicting row often
  does not exist yet - two requests booking an employee's first job of the day
  have nothing to lock. Predicate locking is what advisory locks stand in for.
- **Application-level mutex.** Wrong the moment a second API process exists.

### Costs accepted

`hashtext()` maps a UUID onto 32 bits, so two employees can collide on a lock
key. The result is a little unnecessary serialisation, never a wrong answer.

The lock is taken *after* the cheap eligibility checks (organization, active,
qualified, working hours), so a request that was never going to succeed does not
serialise anyone.

### Deploying the constraint onto existing data

Adding the constraint fails if any overlapping jobs already exist - as they did
in this repository's own seed data, which had 26 overlapping pairs before phase 4.
The migration deliberately does not clean up: an operator has to reconcile real
double-bookings first, because silently deleting or moving someone's booked work
would be worse than a failed migration. The seed is now conflict-aware and
availability-aware, so it produces data the constraint accepts.

## 2. Availability semantics

Weekly windows and overrides are stored as **local wall-clock times** in the
organization's timezone; jobs are stored as absolute UTC instants. Evaluation
converts one to the other explicitly (`services/availability.py`).

Storing wall-clock is the point: "Maria works 9-5" stays true across a
daylight-saving change, whereas a window pinned to a UTC offset would silently
shift her start by an hour twice a year. There are tests for exactly that.

### Override precedence

Exactly one override may exist per employee per date, which keeps precedence
unambiguous:

| Situation | Result |
| --- | --- |
| Override with `available = false` | The date is blocked outright |
| Override with `available = true` | Its hours **replace** the weekly schedule for that date |
| No override | The weekly schedule for that weekday applies |

A special-availability override therefore also *withdraws* the normal hours - it
stands in for them rather than adding to them. That is the reading the PRD
describes, and it is what makes "working a one-off evening instead of my usual
day" expressible. There is a test asserting both halves.

### Known limits

- Windows are day-bounded (`end_time > start_time`), so an appointment crossing
  local midnight cannot be covered. Overnight work would need windows that span
  dates; no such shift exists in the demo, and the refusal is explicit rather
  than silent.
- Availability is not versioned. Editing a schedule does not re-validate jobs
  already assigned, which is the right behaviour for history but means an admin
  can create a schedule that its own existing jobs fall outside.

## 3. Ranking

`services/recommendations.py` ranks the active, qualified employees by a total
lexicographic key:

```
(not assignable, jobs_today, scheduled_minutes_today, full_name, employee_id)
```

Deterministic by construction - the id makes the key total, so two candidates can
never compare equal and the order cannot wobble between requests. There is a test
that runs it five times and asserts an identical order.

Unqualified and deactivated employees are excluded outright; everyone else is
returned *including* those who are off or busy, each carrying the reason. The
admin should see why someone ranks low rather than wonder where they went. This
is ordinary business logic, not a model.

## 4. Where phase 4 plugged in

No workflow, route or phase 3 test changed. `AvailabilityPolicy` extends
`QualificationPolicy` and is installed as the default policy; confirmation,
reschedule and reassign already routed through
`SchedulingPolicy.check_assignment` inside their transaction, so all three
inherited availability, conflict detection and locking at once.

The phase 3 note about `FOR UPDATE` and eager-loaded outer joins still applies and
is unchanged: `load_booking(for_update=True)` and `get_job(for_update=True)` pass
`.options(lazyload("*"))`. The new advisory lock sidesteps the issue entirely by
not locking rows at all.

## 5. Tests run against migrations, not metadata

`tests/conftest.py` now builds the schema with `alembic upgrade head` instead of
`Base.metadata.create_all`. The scheduling guarantee lives in an extension and an
exclusion constraint, neither of which SQLAlchemy metadata knows about - so
`create_all` would have produced a database missing the very constraint the
concurrency tests exist to prove. The tests would have passed and proved nothing.
