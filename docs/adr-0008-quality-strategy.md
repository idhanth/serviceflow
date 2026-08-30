# ADR 0008 - How this system is tested

Status: accepted
Date: 2026-08-30

Phase 8 added no features. It added the evidence that the previous seven phases
work: browser tests against the real application, contention tests that go wider
than one race, failure tests that break real dependencies, and load runs whose
numbers were measured rather than hoped for.

## 1. The shape of the suite

```
  load (k6)              3 scenarios, run on demand against an isolated database
  end-to-end (Playwright) 28 tests, real browser -> Next.js -> API -> Postgres
  stress / concurrency    81 tests, real threads against real PostgreSQL and Redis
  integration (pytest)    the bulk: routes, services, tenant isolation, failures
  unit (pytest)           pure logic - windows, transitions, ranking, validation
```

The lower four run in `uv run pytest` and finish in about ninety seconds. Load
runs are a separate command on purpose: nobody should wait a minute for k6 to
find out whether their booking validator works.

## 2. End-to-end tests drive the browser, not the services

Playwright talks to the running Next.js app. Where a check needs to read data
back, it goes through the app's own `/api/proxy` route **from inside a page**,
using the signed-in session - not a bearer token minted in the test.

That was forced by a real constraint and turned out to be the right design. The
session cookie is `httpOnly` and `Secure`; browsers make a localhost exception
and send it over http, but Playwright's own request contexts do not, so
out-of-band calls came back 401. Running `fetch` inside the page fixed it and
also guarantees a test can never see data the UI could not - the token is
attached server-side, exactly as in production.

Three sessions are established per run (admin, employee, the seeded demo
customer) plus one sign-up for a customer created fresh for that run. Sign-in is
rate limited, deliberately, and the suite leaves that limiter switched on, so
tokens are cached rather than re-fetched per assertion.

## 3. Serial, ordered, and self-sufficient

`fullyParallel: false`, one worker, no retries. The suite hands work between
roles - a customer books, an admin confirms, an employee finishes - and spec
files are numbered so they run in that order. Retries are off because a flaky
test is a defect in the test, and hiding it behind a rerun is how a suite stops
meaning anything.

Each spec still builds its own preconditions, so any file can be run alone.
Several rules came out of failures rather than foresight:

- **Slots are computed in the shop's timezone**, not the machine's and not UTC.
  Availability is local wall-clock; a slot picked as "15:00 UTC" lands at 8am in
  Los Angeles, before most of the team starts, and every candidate comes back
  unavailable - a test that fails while the product is right.
- **Slots are found, not assumed.** Fixed times collide with the previous run's
  bookings, which the product correctly refuses. The helper reads the
  technician's calendar and picks an hour they are actually free.
- **Rows are found by paging**, because shared queues grow as the suite runs.
- **Identity is unique per run.** The run's customer carries the run id in their
  surname, so a spec can never act on a row an earlier run left behind.
- **Waits are on conditions**, never on the clock: a network response, a page
  indicator, a rendered element. There is no `sleep` in the suite.

## 4. Load runs never touch the demo database

`scripts/load.sh` builds and seeds `serviceflow_load`, starts a second API on
:8100 against it, and runs k6 there. The development database is not a
participant, so a run cannot damage the data the app is demonstrated with.

Rate limiting is switched off for load runs. With it on, the run would measure
the limiter refusing traffic rather than the system serving it; the limiter's own
behaviour is proved separately, against real Redis, in
`tests/test_stress_ratelimit.py`.

Every write carries its own idempotency key, as a real client would, which is
what makes the post-run invariant check meaningful: `load/invariants.sql` asks
the database whether any key produced two bookings, whether any confirmed
booking lacks exactly one job, whether any employee ended up double-booked, and
whether anything crossed a tenant boundary.

## 5. Congestion is not a defect

Load testing changed the product twice, and both changes were about telling the
truth under pressure rather than about speed.

At 100 concurrent users the connection pool was exhausted and every waiting
caller received **500 Internal Server Error**. That is the wrong thing to say:
it tells a client the request can never work, which invites an immediate retry
into a queue that is already too long. Pool exhaustion and a database that
refuses connections now return **503 with `Retry-After`**.

The mapping is deliberately narrow. Only failures to obtain a usable connection
count as congestion; a query that fails for any other reason - a deadlock, a
constraint, a bug - is still an unhandled error, because it is one. There is a
test for each side of that line.

The second change: SQLAlchemy's pool wait defaulted to 30 seconds, and a request
waiting that long holds a worker thread the whole time. Under saturation the
server starved itself of threads and throughput fell to 2 requests per second.
Waiting 5 seconds instead - `DATABASE_POOL_TIMEOUT` - made the same hardware
serve 15 req/s while shedding the excess, and with a pool sized for the
concurrency, 367 req/s with no errors at all.

## 6. What the numbers mean, and what they do not

Everything in the README's load table was measured on one laptop: a single
PostgreSQL instance with `max_connections = 100`, the API, the database and k6
all competing for the same CPU. That ceiling, not the application, is what stops
500 concurrent users from being served here.

The honest reading is: at 100 concurrent users the system is comfortable
(367 req/s read-heavy, p99 376ms, no errors); at 500 on this machine it is not,
and what it does instead is refuse work politely and stay correct - which the
invariant checks confirm after every run.

No target was set and then met. The numbers are whatever the machine produced.
