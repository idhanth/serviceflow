# ADR 0007 - Idempotency, the audit trail, rate limits and error hygiene

Status: accepted
Date: 2026-08-30

Phase 7 is about the guarantees that only matter when something goes wrong: a
double-submitted booking, a disputed change, a scripted signup flood, an
unexpected exception. Each of the decisions below chose the option the database
or Redis can enforce over the one the application merely intends.

## 1. Idempotency is a table, not a cache

`POST /bookings` accepts an `Idempotency-Key` header. The key, the caller, the
organization and a SHA-256 fingerprint of the canonical payload are stored in
`idempotency_records`, with a unique constraint on
`(organization_id, user_id, key)`.

That constraint is the mechanism, not a safety net. The claim is written on a
savepoint inside the booking's own transaction:

```python
savepoint = db.begin_nested()
db.add(record)
try:
    savepoint.commit()          # PostgreSQL decides who won the race
except IntegrityError:
    savepoint.rollback()
    competitor = db.scalar(...)  # replay it, or reject as a conflict
```

Two simultaneous requests with the same key therefore cannot both proceed: one
inserts, the other loses the constraint and reads the winner's outcome. A
process-local dictionary or a Redis SETNX would both be wrong here - the first
because it does not survive more than one worker, the second because it is not
in the transaction that creates the booking, so a crash between the two leaves a
key claimed for a booking that never existed.

Outcomes:

| Situation | Response |
| --- | --- |
| New key | 201, the booking is created |
| Same key, same payload | 200 with `Idempotent-Replay: true` and the original body |
| Same key, different payload | 409 `IDEMPOTENCY_CONFLICT` |
| Key outside 8-200 chars or containing anything but `A-Za-z0-9._:-` | 422 `VALIDATION_FAILED` |
| No key at all | 201, no replay protection - the header is opt-in |

**Retention is 24 hours** (`idempotency.RETENTION`). The window has to outlive a
user's retries and a client's queued request, not a billing period; keeping keys
forever would turn a convenience table into an unbounded log of who requested
what. `purge_expired()` runs on the Celery beat schedule, and `expires_at` is
indexed so the sweep stays cheap. A key reused after expiry is simply a new key.

The response body is stored as JSONB so a replay returns exactly what the first
attempt returned. Nothing sensitive is in a booking response, but the same table
must not be reused for endpoints where that stops being true.

The frontend derives its key from the payload plus a per-mount nonce
(`booking-wizard.tsx`), so retrying the same booking reuses one key while editing
any field earns a new one. Disabling the submit button remains a nicety; this is
the guarantee.

## 2. The audit trail is append-only in PostgreSQL

`audit_logs` has no `updated_at`, because a row is never updated. That is
enforced by a trigger, not by convention:

```sql
CREATE TRIGGER audit_logs_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_are_immutable();
```

Both statements raise `restrict_violation`. Application code, a psql session and
a future migration author all hit the same wall.

**Known limit:** `TRUNCATE` fires statement-level triggers, not row-level ones,
so a superuser can still truncate the table. Defending against that is a matter
of role grants, not schema, and would require a database role the local
development setup does not have. It is recorded here rather than hidden. The test
suite truncates deliberately for exactly this reason.

Entries are *staged* on the caller's session - `audit.record()` contains no
`commit()`. An action that rolls back leaves no claim that it happened, and an
action that commits cannot commit without its audit row.

The actor is `CurrentUser`, never a request field. There is no route that accepts
an actor or an organization for an audit entry.

**Metadata is a summary, never a payload.** `_safe_metadata()` drops any key
containing `password`, `token`, `secret`, `authorization`, `signature`,
`api_key`, `cookie`, `credential` or `x-amz`, and truncates values over 200
characters. Note content is deliberately absent: the trail records that a note
was added and by whom, not what it said, because internal notes are exactly the
thing customers must never see.

## 3. Rate limiting is a Lua script on Redis

One round trip does INCR, a conditional EXPIRE and a TTL read atomically. Two
processes cannot interleave between the increment and the expiry, which is the
failure a naive `incr` then `expire` has when the first request dies between the
two - a key with no TTL, and a limiter that never resets.

Identity is explicit per limiter class: unauthenticated limits key on the client
address, authenticated limits on `org:{id}:user:{id}`. Organizations and users
therefore cannot spend each other's budget.

### Trusted proxies

`trusted_proxy_count` (default **0**) says how many proxies sit in front of the
API. At 0, `X-Forwarded-For` is ignored entirely and the socket address is used.
Set it to the real number of hops in front of the deployment; the identity is
then taken that many entries from the right of the header. Blindly trusting the
leftmost value would let anyone mint an unlimited number of identities with one
header, which is worse than having no limiter at all.

### Outage policy, per class

Redis being down must not mean the same thing everywhere:

| Limiter | Window | Policy without Redis |
| --- | --- | --- |
| `signup` | 5 / hour | **fail closed** |
| `login` | 10 / 15 min | **fail closed** |
| `booking_create` | 20 / hour | fail open |
| `photo_presign` | 60 / 10 min | fail open |
| `search` | 120 / min | fail open |

The unauthenticated, abuse-attractive endpoints refuse rather than run
unprotected: a signup flood during a Redis outage is a worse outcome than a
degraded signup form. The authenticated ones fail open, because a known user
being unable to book while Redis is restarting is an outage the limiter caused,
and the damage a signed-in customer can do is bounded by everything else in the
system. Both directions are tested against a Redis that raises.

Limits live in `services/ratelimit.py:LIMITS` and are switchable as a whole with
`RATE_LIMITING_ENABLED`.

## 4. Errors say what happened, never how

Every failure renders the same envelope with a stable code, a sentence written
for a person, and a request id. The unhandled-exception handler logs the
traceback with `exception_type` and returns *"Something went wrong on our end."*
- no exception text, SQL, stack frame, filesystem path or provider response ever
crosses the boundary.

Validation is normalized to a `fields` map. Pydantic's `input` and `ctx` are
dropped on the way, because for a rejected password `input` is the password.

A foreign-tenant resource still returns exactly what a nonexistent one returns.
Nothing in Phase 7 changed that, and the tenant-isolation suites still assert it.

## 5. Correlation actually reaches the logs

Two bugs were found here by looking at real log output rather than at tests:

1. `BaseHTTPMiddleware` runs the downstream app in a **separate anyio task**, so
   context set inside a request never propagated back out to the middleware. It
   is now a plain ASGI callable.
2. FastAPI runs synchronous dependencies and endpoints with `run_in_threadpool`,
   which **copies** the context; the `user_id` the auth dependency set updated a
   copy that was discarded. So every authenticated request logged `user_id: null`
   even after fix (1).

The context now holds one mutable dict, bound once per request before any child
context forks (`core/context.py`). A write from a worker thread is visible to the
middleware that logs the response. There is a test that fails if either
regression returns.

The chain is `request_id` -> business event -> Celery task: `outbox` captures the
context when staging, and `adopt_context()` takes it on inside the worker, so one
id spans the request that caused an email and the task that sent it.

`X-Request-Id` is honoured if a gateway sends one (truncated to 64 characters)
and generated otherwise. Because Starlette's `ServerErrorMiddleware` sits outside
all user middleware, the header is also set on the error envelope itself - the id
in the body and the id in the header always agree.
