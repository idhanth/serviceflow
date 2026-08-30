# ADR 0006 - Background work, email delivery and realtime

Status: accepted
Date: 2026-08-30

## 1. Celery on Redis

Redis is broker and (nominally) result backend. It already runs for the rest of
the stack, and the queue depth here - a handful of emails per booking - does not
justify operating a second message broker.

**Results are ignored** (`task_ignore_result = True`). Nothing consumes them:
the API queues and forgets, and durable state lives in the `notifications` table.
Storing results made the API hold a result-store connection it never read, which
during a Redis outage produced *"the Celery application must be restarted"*
errors about a subsystem the API does not use. Removing it also took the test
suite from 85s back to 39s.

Tasks are bound with `@celery_app.task`, not `@shared_task`. `shared_task` binds
to whatever Celery considers the *current app*, which in the API process is
Celery's default AMQP app unless `celery_app` happens to have been imported - so
every `.delay()` silently failed to queue and only the sweep delivered anything.
This was found by manual verification, not by a test, because the sweep masked it.

`acks_late = True` with `task_reject_on_worker_lost = True`: a task whose worker
dies is redelivered. That is what makes the outbox at-least-once rather than
at-most-once, and it is the right trade for email.

## 2. Notifications as an outbox

Phase 5 established that notifications are staged inside the business
transaction. Phase 6 adds the side effects, strictly after the commit:

```
  stage_email() / stage_event()      during the transaction
              |
           COMMIT
              |
  after_commit listener              queue Celery, publish to Redis
```

`services/outbox.py` owns that. Business services stage; nothing calls Celery or
Redis directly. Neither side effect can fail a request: a booking that committed
has happened, and a broadcast or queue failure must not turn it into an error.

**A rolled-back transaction announces nothing.** The `after_rollback` listener
discards whatever was staged, so a failed confirmation cannot send an email
claiming success. Tested by forcing a mid-transaction failure.

### Broker outage right after the commit

The committed row is still `PENDING`, so `sweep_pending_emails` (every 60s)
re-queues anything older than the stranded threshold. Verified by hand: Redis
killed, booking confirmed successfully, row left `PENDING`, Redis restored, row
delivered by the sweep without intervention.

## 3. Delivery semantics: at-least-once, not exactly-once

The row is locked with `SELECT ... FOR UPDATE SKIP LOCKED` for the duration of
the provider call, so two workers never send the same message concurrently, and a
second worker moves on rather than blocking.

**If a worker dies after the provider accepts the message and before the COMMIT
that marks it `SENT`, the row stays `PENDING` and the message is sent again.**
Closing that window needs a provider with idempotency keys and a two-phase
handshake. Claiming exactly-once here would be false, so the contract is
at-least-once and the duplicate window is documented rather than papered over.

Retries use bounded exponential backoff with jitter (5s base, 600s ceiling, five
attempts). A *permanent* rejection - a refused recipient - is told apart from a
transient one and fails the row immediately rather than retrying five times into
the same wall. Exhausted retries set `status = FAILED` and `failed_at`.

Retries never create a second `Notification` row: the task takes an id and either
settles that row or skips it.

## 4. Email providers

No provider credentials existed on this machine, so development delivers over
**real SMTP to MailPit** - an actual SMTP server with an inspectable mailbox -
rather than pretending a send succeeded. Tests assert against MailPit's API.

Production sets `EMAIL_PROVIDER=resend` and `RESEND_API_KEY`. Both implement one
interface and raise one exception type, so the task has a single failure mode to
reason about. Nothing in booking or job logic knows which is configured.

Emails are rendered from the notification's own `subject` and `body`, which
`services/notifications.py` writes. Nothing reads a `JobNote` or a job's
`internal_notes`, and there is a test asserting internal text never appears in a
delivered message.

Which events email is a product decision, not a technical one: customer-facing
events (confirmed, rejected, rescheduled, cancelled, reminder, job completed) go
to both channels; staff operational alerts stay in-app, because an admin watching
a queue does not want a message per booking request.

## 5. Appointment reminders

24 hours ahead, with the beat running every 5 minutes over a ±90 minute window -
wide enough that a late tick never misses one.

Duplicates are prevented two ways, neither needing a schema change:

1. an existing `APPOINTMENT_REMINDER` for the booking is checked before insert;
2. the whole sweep runs under one transaction-scoped advisory lock, so two beats
   or two workers serialise instead of both finding the same booking unreminded.

Only `CONFIRMED` bookings whose job is still `ASSIGNED` or `IN_PROGRESS` qualify,
so cancelled, rejected and finished appointments are never reminded about. There
is a concurrency test that fires four scheduler runs simultaneously and asserts
exactly one creates the reminder.

## 6. Realtime over SSE

SSE, not WebSockets: everything flows server to client, and the PRD asks for the
simpler primitive absent a real need for bidirectional traffic.

**Events are ephemeral signals, not durable state.** An envelope carries only
`type`, `resource`, `resource_id`, `organization_id`, its recipients and a
timestamp - never record content. The client answers by invalidating a TanStack
Query key and refetching. That is what makes a dropped event harmless: a
reconnecting client refetches and is correct again, with nothing to replay. A
test asserts no field of a booking leaks into an envelope.

Redis pub/sub distributes them, with **one channel per organization**, so a
subscriber never receives another tenant's traffic at all. Not an in-process
emitter: it has to work across several API processes and when a Celery worker is
the thing raising the event.

### Authorization

The connection is authorized once, by the same dependency every other route uses.
`EventSource` cannot send an `Authorization` header, so the browser connects to a
Next.js route handler with its httpOnly cookie and the token is attached
server-side - exactly as for every other request. Moving the JWT somewhere
JavaScript can read it, for the sake of one endpoint, would undo the phase 1
security model.

Delivery is then filtered per event: explicit recipients by user id, plus roles
for shop-wide operational events. A notification is addressed to one person, so
not even an admin sees someone else's.

### Reconnect and fallback

The stream sends `retry: 3000`, so `EventSource` reconnects on its own. The
client also reconnects with capped exponential backoff and only reports trouble
after three consecutive failures - a brief drop is normal and not worth alarming
anyone about. Periodic refetching stays configured as a floor: 5 minutes while
live, 60 seconds when not. Nothing requires a manual refresh to recover.

## 7. What needs Redis, and what does not

| Capability | Without Redis |
| --- | --- |
| Database-backed reads and writes | Work normally |
| Booking, confirmation, job lifecycle | Work normally; the commit is what matters |
| In-app notifications | Written and readable as usual |
| Email dispatch | Queued into the outbox; delivered when Redis returns |
| Realtime | Dark; clients fall back to refetching |
| `/health` | `ok` |
| `/ready` | `503`, naming Redis |

Verified by hand: with Redis stopped, `/ready` returned 503 while `/health`
stayed `ok`, a booking was created successfully, its notifications persisted, and
the API served reads throughout.

## 8. Observability

`GET /api/v1/infrastructure` (admin, organization-scoped) reports pending, sent
and failed email counts, Celery queue depth, and realtime subscriber count -
enough to notice stuck email or a dark event bus without shelling into a box.
The broader structured-logging work stays in phase 7.
