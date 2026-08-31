# ADR 0010 - Production deployment

Status: accepted
Date: 2026-08-31

Phase 10 added no product behavior. It decided where each part of the system
runs, and what stops the production configuration from quietly being wrong.

The binding constraint was cost: the whole deployment must be free, and no
decision below trades correctness for that. Where free hosting could not do the
job properly, the answer was to move the workload, not to weaken it.

## 1. The frontend cannot be the only server

Everything else follows from one decision made back in phase 1: the browser
never calls the API. It calls the Next.js server on its own origin, which
forwards server-side.

That is what allows the session cookie to be `Secure`, `HttpOnly`, `SameSite`
and first-party at once. The alternative — the browser calling `api.domain.com`
directly — needs either a cross-site cookie or a token in JavaScript-reachable
storage. Both were rejected in phase 1 and neither becomes acceptable because
deployment is inconvenient.

So the deployment has a server-side hop by construction, and the question was
only where the API behind it lives.

## 2. The API is not serverless, because the worker cannot be

Vercel runs the frontend well and free. It cannot run this API:

- **Celery beat must run continuously.** Reminder scheduling is a clock, not a
  request.
- **Workers must outlive the request that queued the job.** The transactional
  outbox commits work in the request and drains it afterwards; with a
  request-scoped runtime nothing would drain it.
- **Rate limiting and realtime need a persistent Redis connection**, not one
  established per invocation.

Rewriting the worker as cron-triggered HTTP endpoints would have fit a
serverless host, at the price of making the queue fictional — retries, backoff
and `acks_late` all become someone else's problem. The queue is real, so it
needs a process that stays up.

An always-free small ARM VM (Oracle Cloud Ampere A1) runs uvicorn, the Celery
worker and Celery beat as three separate systemd units. Measured footprint is
about 250 MB RSS for all three, against 12 GB available.

The cost of this choice is honest and worth stating: it is a single machine with
no redundancy, on a free tier that may reclaim idle instances, and it is the one
piece of this deployment that is not managed by anyone.

## 3. Worker and beat are separate units

They could share a process — `celery worker --beat` exists. They do not, for two
reasons. Restarting the worker to pick up new code would restart the scheduler
with it, and beat's schedule file would then live inside a release directory
that deployment replaces. Beat keeps its state in `/var/lib/serviceflow`,
outside any release, and can be restarted independently of the workers.

## 4. Trusting a forwarded address requires making it unforgeable

The API identifies unauthenticated callers by IP for rate limiting. Behind two
proxies, the real address only exists in `X-Forwarded-For` — a header any client
can write. Trusting it naively means the login limiter can be evaded with one
extra header.

`TRUSTED_PROXY_COUNT` already existed to read the correct hop (`chain[-hops]`),
and it is set to 2 here: the frontend writes the browser's address, Caddy
appends its peer. But reading the right position only helps if untrusted callers
cannot reach the API at all. Two things enforce that:

- uvicorn binds to loopback; the firewall opens only 80 and 443.
- The frontend sends a shared `X-Proxy-Token`. Caddy rejects requests without
  it, and **the API checks it again independently**, so a mistake in the edge
  configuration does not silently expose the service. The check uses a constant
  time comparison and exempts only `/health` and `/ready`.

This is defense in depth rather than belt-and-braces: the edge and the
application fail differently, and the header is worthless without both.

## 5. Pool sizing is a deployment decision, not a default

Three processes hold connection pools. `3 x (5 + 5) = 30` is the real ceiling to
check against the provider's limit, and it is written down in the environment
file next to the numbers that produce it, because that arithmetic is exactly
what gets forgotten when someone later adds a worker.

Phase 8 established that saturation must degrade deliberately: `pool_timeout` of
5 seconds, and exhaustion mapped to **503 with `Retry-After`** rather than a
generic 500. That behavior is a production requirement, not a test artifact, so
the production configuration is sized to keep it — a larger pool against a
smaller database limit would move the failure from the app, where it is
explicit, into the driver, where it is not.

## 6. The demo's auth is opt-in, not accidental

`AUTH_PROVIDER=dev` issues local tokens. Shipping that to production by accident
would be a serious hole, so the API refuses to start in production with the dev
provider unless `PUBLIC_DEMO_MODE=true` says the deployment's logins are
published deliberately.

A flag that can be set is not a control by itself, so the API also logs its
deployment configuration at startup and warns about each unsafe setting it finds
— debug mode, demo mode, localhost in CORS, a zero proxy count, SMTP in
production. The warning is not suppressible.

## 7. Seeding is never automatic

The seed is idempotent - it upserts rather than replacing, so re-running it is
safe - but it writes a synthetic book of business into whatever database it is
handed. That is not something a deployment should ever do on its own, so neither
`deploy.sh` nor any systemd unit calls it, and it is not reachable over HTTP at
all. Setting up a demo means an operator running it once by hand against a
database they name. There is no path by which a deployment, a restart, or a
failed migration seeds a live database.

## 8. Email is genuinely delivered, and still at-least-once

Production sends through Resend rather than capturing to MailPit. The outbox
guarantees a queued email is eventually attempted and retried on failure; it
does not guarantee exactly one delivery, and a retry after a provider timeout
can send twice. Phase 6 documented that, and production does not change it.
