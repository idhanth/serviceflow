# Benchmarks

Two benchmarks back the claims in the README. Both are scripts in this
repository, both write JSON into `benchmarks/results/`, and every number on this
page is generated from those files by `benchmarks/render_docs.py`. A test
(`apps/api/tests/test_benchmark_claims.py`) fails if the page and the files
disagree, so a number here cannot be edited by hand or left behind by a rerun.

| Benchmark | Question it answers | Script | Result |
| --- | --- | --- | --- |
| Tenant isolation | Does any invalid write get through? | `scripts/bench-isolation.sh` | `benchmarks/results/tenant_isolation.json` |
| Load | How does the API behave under a realistic authenticated mix? | `scripts/load-test.sh` | `benchmarks/results/load_test.json` |

## Tenant isolation

```bash
./scripts/bench-isolation.sh
```

The script drops and rebuilds a throwaway `serviceflow_bench` database, runs the
migrations, starts an API on port 8200 against it, and builds four tenants with
their own owners, dispatchers, analysts, technicians, customers, services and
anchor bookings. It then **generates** invalid writes from that data - the count
is a product of the configuration (tenants, technicians, slots, sample size, race
rounds and race size), never a constant - and fires them through the real HTTP
API with 16 concurrent clients, plus raw SQL for the database-level attacks.

<!-- benchmark:isolation-summary:start -->
| Invalid attempts | Blocked | Unexpected successes | Server errors | Invariant violations |
| ---: | ---: | ---: | ---: | ---: |
| 3,061 | 3,061 | 0 | 0 | 0 |

Alongside the attacks, 128 legitimate control writes succeeded (result: **PASS**, commit `ebc247e`, 2026-09-14T19:46:03+00:00).
<!-- benchmark:isolation-summary:end -->

<!-- benchmark:isolation-categories:start -->
| Category | Attempted | Blocked | Unexpected | How it was refused |
| --- | ---: | ---: | ---: | --- |
| Exact duplicate bookings | 288 | 288 | 0 | `BOOKING_CONFLICT` 288 |
| Overlapping technician bookings | 576 | 576 | 0 | `BOOKING_CONFLICT` 576 |
| Concurrent double-booking races (losing requests) | 224 | 224 | 0 | `BOOKING_CONFLICT` 224 |
| Cross-tenant customer in a booking | 192 | 192 | 0 | `NOT_FOUND` 192 |
| Cross-tenant technician in a booking or assignment | 192 | 192 | 0 | `NOT_FOUND` 192 |
| Cross-tenant service in a booking | 192 | 192 | 0 | `NOT_FOUND` 192 |
| Reading or changing another tenant's records by id | 520 | 520 | 0 | `NOT_FOUND` 504, `TENANT_ACCESS_DENIED` 16 |
| Actions outside the caller's role | 397 | 397 | 0 | `INVALID_ROLE` 324, `NOT_FOUND` 73 |
| Raw SQL writes that skip the API | 480 | 480 | 0 | `fk_bookings_organization_id_customers` 80, `fk_bookings_organization_id_services` 80, `uq_bookings_no_duplicate_open` 80, `fk_jobs_organization_id_employees` 80, `jobs_no_overlapping_assignments` 80, `InsufficientPrivilege` 80 |
<!-- benchmark:isolation-categories:end -->

What each category does:

- **Exact duplicates** resubmit an existing open booking - same customer, service
  and start - without a technician, with one, and from a second staff account.
  The API refuses them, and the partial unique index
  `uq_bookings_no_duplicate_open` would refuse them if it did not.
- **Overlaps** book a technician, for a different customer, at the same start as
  a job they already hold or 15, 30 or 45 minutes after it or 30 or 45 minutes
  before it. The scheduler refuses with a readable `BOOKING_CONFLICT`; the
  exclusion constraint `jobs_no_overlapping_assignments` is the final guard.
- **Concurrent races** release several requests for the same free slot from a
  shared barrier. Exactly one must win; the winners are counted as *controls*, the
  losers as blocked attempts.
- **Cross-tenant customer, technician and service** reference another tenant's
  row by id in a booking or assignment. Composite `(organization_id, id)` foreign
  keys make such a row impossible to store even if application code forgot to
  check.
- **Resource access** reads, updates, cancels and archives another tenant's
  records by id, and names another organization in `X-Organization-Id`.
- **Unauthorized roles** act inside their own tenant beyond their permissions: a
  technician or analyst booking, a customer booking for someone else, an analyst
  changing jobs, a technician starting a colleague's job, non-owners changing
  settings or granting roles, and an owner calling platform administration.
- **Database-level bypass** skips the API and writes SQL as the application role.
  Five attacks run with the row level security bypass switched on, so nothing
  but the schema stands in the way: a booking that mixes one tenant's customer or
  service into another tenant, a duplicate open booking, another tenant's
  technician put on a job, and a job moved on top of a technician's existing job.
  Composite foreign keys, the partial unique index and the exclusion constraint
  refuse them. The sixth runs under one tenant's RLS context and inserts a row
  labelled with another tenant, which the policy's `WITH CHECK` refuses. Each
  statement must target exactly one row, so an attack that matched nothing
  cannot pass for a refusal.

A run **passes** only if every attempt is refused, no attempt produces a `5xx`,
every control write (anchor bookings and race winners) succeeds - so a system
that refused everything cannot pass - and a final set of SQL invariants finds no
overlapping live jobs, no cross-tenant references, no duplicate open bookings and
no booking without exactly one job. CI reruns the benchmark on every push.

The exact attempt count moves by a few between runs. Two role checks - a
technician starting a *colleague's* job, and a customer cancelling *someone
else's* booking - only apply to sampled bookings that belong to someone else, and
which sampled bookings those are depends on the generated ids. Every other
category is fixed by the configuration.

## Load test

```bash
./scripts/load-test.sh run 100 60s                      # rebuilds the dataset, then runs
WORKERS=6 POOL_SIZE=8 MAX_OVERFLOW=4 ./scripts/load-test.sh run 100 60s
```

The runner never touches the development database. Every run rebuilds
`serviceflow_load` from scratch through the real migrations, so one run's new
bookings and job updates cannot collide with or flatter the next.

**Dataset.** `benchmarks/load/seed_dataset.py` creates 25 tenants, each with an
owner, a dispatcher and an analyst, 20 technicians with weekly hours, 400
customers, 8 services and 2,000 bookings with their jobs. Each technician's work
is laid out in three daily slots from about two months ago to two months ahead:
past work is mostly completed with some cancellations, upcoming work mostly
scheduled with some pending and cancelled, so list, schedule and dashboard
queries have realistic work to filter.

**Workload.** `benchmarks/load/mixed.js` signs in each tenant's dispatcher once
during setup (so the run measures the endpoints, not password hashing), then each
virtual user stays in one tenant and loops with no think time over a weighted
mix:

| Share | Request |
| ---: | --- |
| 25% | `GET /bookings` - paginated list, with and without status and timeframe filters |
| 20% | `GET /jobs` - paginated list, with and without status and timeframe filters |
| 15% | `GET /customers` - paginated list |
| 15% | `GET /schedule` - the tenant's day view for a date within a week either side of today |
| 10% | `POST /bookings` - a new booking, which writes the booking and its unassigned job and stages audit and notification rows in the same transaction |
| 10% | `PATCH /jobs/{id}` - moves a scheduled job to in progress, then to completed with a note |
| 5% | `GET /dashboard` |

Every request is authenticated and tenant-scoped exactly as in production. The
writes are built so a correct server never has a reason to refuse them: each new
booking starts at a minute no other request uses, and each virtual user walks its
own slice of scheduled jobs through legal transitions. Rate limiting is off for
the API under test so the run measures the system serving traffic, not the
limiter refusing it - the limiter has its own tests against real Redis. Any `4xx`
or `5xx` counts as an error, and nothing is marked as expected.

### Result

Identical runs on a shared machine do not produce identical numbers, so the
published result is not a single run. `./scripts/load-test.sh final` makes three
runs of the chosen configuration, each on a freshly rebuilt dataset, and publishes
the run with the median throughput - a rule fixed before the runs - while keeping
all three:

<!-- benchmark:load-repeats:start -->
| Run | Throughput | p50 | p95 | p99 | Errors (failed requests) | Requests | Peak connections | Published |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| run-1 | 363.4 req/s | 229.4 ms | 508.4 ms | 745.9 ms | 0.00% (0) | 23,143 | 61 |  |
| run-2 | 378.8 req/s | 210.0 ms | 531.8 ms | 790.3 ms | 0.00% (0) | 24,131 | 61 | yes |
| run-3 | 380.5 req/s | 209.8 ms | 533.2 ms | 792.8 ms | 0.00% (0) | 24,218 | 61 |  |
<!-- benchmark:load-repeats:end -->

The published run:

<!-- benchmark:load-summary:start -->
| Throughput | p50 | p95 | p99 | Error rate (failed requests) | Requests |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 378.8 req/s | 210.0 ms | 531.8 ms | 790.3 ms | 0.00% (0) | 24,131 |

100 concurrent virtual users for 60s, no think time, against 25 tenants, 50,000 bookings and 50,000 jobs. 4 API workers, pool 10 + 5 per worker; peak 61 PostgreSQL connections. Apple M5, 16 GB, PostgreSQL 16.15, Redis 8.10.1; everything on one machine (commit `ebc247e`, 2026-09-14T19:44:27+00:00).
<!-- benchmark:load-summary:end -->

Per endpoint:

<!-- benchmark:load-endpoints:start -->
| Endpoint | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| `GET /bookings` | 189.3 ms | 461.7 ms | 687.6 ms |
| `GET /customers` | 186.6 ms | 488.7 ms | 726.9 ms |
| `GET /dashboard` | 257.2 ms | 575.8 ms | 821.6 ms |
| `GET /jobs` | 185.9 ms | 472.4 ms | 705.4 ms |
| `GET /schedule` | 196.3 ms | 489.7 ms | 727.7 ms |
| `PATCH /jobs` | 260.7 ms | 675.8 ms | 1,009.1 ms |
| `POST /bookings` | 300.8 ms | 671.1 ms | 960.3 ms |
<!-- benchmark:load-endpoints:end -->

Configuration:

<!-- benchmark:load-configuration:start -->
| | |
| --- | --- |
| Hardware | Apple M5, 10 logical CPUs, 16 GB RAM (Darwin 25.5.0) |
| Topology | API, PostgreSQL, Redis and k6 on the same machine |
| PostgreSQL | 16.15 (max_connections 100) |
| Redis | 8.10.1 |
| Load generator | k6 v1.4.0 (commit/a9f9e3b28a, go1.25.4, darwin/arm64) |
| Dataset | 25 tenants, 500 technicians, 10,000 customers, 200 services, 50,000 bookings, 50,000 jobs, 10,575 users |
| Concurrency | 100 virtual users, none (closed loop) |
| Duration | 60s |
| API | 4 uvicorn workers, rate limiting off (the limiter is tested separately) |
| Pool (per worker) | pool_size=10, max_overflow=5, pool_timeout=5s, pool_recycle=1800s, pre_ping, at most 60 connections from the API |
| Connections observed | peak 61 total, peak 10 active, mean 4.0 active |
<!-- benchmark:load-configuration:end -->

The raw k6 summary the report was built from is committed next to it (its path is
the `raw_summary` field), and the claims test checks the headline figures against
it.

### Pool and worker tuning

The API, PostgreSQL and k6 share one machine's cores, so the question was how
many API processes it can usefully run, and how large each one's connection pool
should be, without exceeding PostgreSQL's connection limit or leaving requests
queueing for a connection. Four configurations were measured, each once, on the
final code:

<!-- benchmark:load-tuning:start -->
| Workers | Pool per worker | Max API connections | Throughput | p50 | p95 | p99 | Errors (failed requests) | Peak connections |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 10 + 5 | 30 | 252.0 req/s | 111.1 ms | 264.6 ms | 10,021.8 ms | 2.00% (322) | 31 |
| 4 | 10 + 5 | 60 | 414.4 req/s | 177.7 ms | 540.4 ms | 805.0 ms | 0.00% (1) | 59 |
| 6 | 8 + 4 | 72 | 215.8 req/s | 335.5 ms | 1,176.7 ms | 1,949.7 ms | 0.00% (0) | 70 |
| 8 | 6 + 4 | 80 | 315.9 req/s | 191.3 ms | 899.0 ms | 1,601.2 ms | 0.00% (0) | 74 |

Each row is one run of 100 virtual users for 60s against a freshly rebuilt dataset, from `benchmarks/results/tuning/`. The headline result uses 4 workers with a pool of 10 + 5, measured again in separate runs.
<!-- benchmark:load-tuning:end -->

Four workers with a pool of 10 + 5 had the highest throughput and was chosen for
the published runs.

Two workers were too few. With 100 users queued on 30 connections, some requests
waited out the 5-second `pool_timeout` and were refused - which is where that
row's roughly 10-second p99 comes from. A diagnostic rerun of that configuration
with failure logging (not one of the published results) showed what the errors
were: 364 were `503 DEPENDENCY_UNAVAILABLE`, each logged by the API as "refusing
work at capacity: pool exhausted", and the other 8 were `409
INVALID_STATE_TRANSITION` on job updates. The scenario moves each job from
scheduled to in progress to completed and assumes the previous step succeeded, so
once updates are refused it asks for transitions that are no longer legal. No
failure of either kind occurred in the published runs. Adding processes beyond that did not help on this machine:
each extra API process competes with PostgreSQL and the load generator for the
same cores. Single runs vary (compare the tuning row for the chosen
configuration with the three published runs above), so the table shows which
configurations are clearly worse, not a precise ranking.

Pool arithmetic: the API can open at most `workers x (pool_size + max_overflow)`
connections, which has to stay under `max_connections` with room for migrations,
Celery and administration. The observed peak includes the runner's own
monitoring connection. `pool_timeout` stays at 5 seconds so that genuine
exhaustion surfaces as a `503` with `Retry-After` rather than requests silently
stacking up behind the pool.

Changes made while profiling:

- **One engine per process.** Sync routes run on a thread pool, and the first
  burst of requests after a worker started reached the lazy engine initialiser
  concurrently, so several threads each built an engine with its own pool. The
  symptom in early load runs was more PostgreSQL connections than
  `workers x (pool_size + max_overflow)` allows. Initialisation now takes a lock,
  and every run on this page was measured after the fix.

- **One query for the caller.** Authentication loaded the user and then their
  memberships separately on every request; it is now one outer join.
- **No empty tenant round trip.** The row level security listener used to run a
  `set_config` statement at the start of every transaction, including ones with
  no tenant to set. A transaction-local setting already starts empty - the
  fail-closed state - so the statement now runs only when there is a tenant or an
  explicit bypass to apply.
- **Stale rows under `FOR UPDATE`.** Locking queries now use
  `populate_existing=True`, so a lock taken after an earlier read returns the
  row's current state instead of the session's cached copy. This was a
  correctness fix (it closed a double-confirmation race) that the load test's
  write paths exercise.

### Query plans

`benchmarks/load/explain_queries.py` calls the load test's endpoints through the
real application as one tenant's dispatcher, records every SELECT they send, and
reruns each under `EXPLAIN (ANALYZE, BUFFERS)` with the same parameters and row
level security context. The plans are committed in
`benchmarks/results/query_plans.txt`. What they show:

- **Authentication is one indexed lookup** - the user by `auth_provider_id` joined
  to their memberships by `user_id`.
- **Lists on the large tables start from a tenant-leading index**
  (`ix_bookings_organization_id_status`, `uq_bookings_no_duplicate_open` for open
  bookings, `ix_jobs_organization_id`, `ix_customers_organization_id_created_at`)
  and order the page with a top-N heapsort rather than sorting the tenant's whole
  table. Related customers, users, jobs and employees are fetched by primary key
  or by the `one_job_per_booking` unique index.
- **The sequential scans are on small tables only**: a tenant's handful of
  services, its employees, the single organization row and an empty overrides
  table, where an index would not be cheaper. None of the 50,000-row tables is
  scanned sequentially.
- **Row level security adds a filter, not a different plan.** The policy's
  `organization_id` predicate appears alongside the application's own tenant
  filter, which the same indexes already satisfy.

Timings inside the plans are from single executions and are not quoted as
results.

## Summary

The project's headline claims, generated from the same result files:

<!-- benchmark:resume-bullets:start -->
- Built multi-tenant booking, scheduling and job-tracking workflows for 7 user roles (platform admin, owner, manager, dispatcher, technician, customer, read-only analyst) in one FastAPI + Next.js platform.
- Blocked all 3,061 tested duplicate, overlapping, cross-tenant and unauthorized booking attempts (0 unexpected successes across 4 tenants) by enforcing isolation in PostgreSQL with composite tenant foreign keys, an exclusion constraint and row level security.
- Sustained 378.8 req/s at 531.8 ms p95 with 0.00% errors in k6 load tests of an authenticated read/write mix over 50,000 bookings, after profiling endpoints and tuning connection pools.
<!-- benchmark:resume-bullets:end -->

## Limits of these numbers

- **One machine.** The API, PostgreSQL, Redis and k6 share the same CPU cores, and
  the machine was an ordinary laptop with other applications open, not an
  isolated benchmark host. The numbers describe this setup; they are not a
  capacity estimate for a server.
- **No network.** Everything runs over loopback, so there is no network latency
  in the figures.
- **One scenario, one duration.** A 60-second closed-loop run shows steady-state
  behaviour under contention; it says nothing about hours-long runs, cache
  eviction or growth of the tables over time.
- **Email and realtime are outside the request path.** Bookings stage outbox rows
  in the same transaction, but delivery runs in Celery and is not part of the
  measured latency.
