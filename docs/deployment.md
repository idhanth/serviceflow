# Deploying ServiceFlow

Everything here is a runbook. **Nothing is deployed yet**: the steps below need
accounts that only the repository owner can create, and this document stops at
that boundary rather than pretending past it.

The target is a genuinely free production deployment — no paid tier is required
by anything described here.

## Topology

```
                    browser
                       |  HTTPS
                       v
        +------------------------------+
        |  Vercel - Next.js server      |   the only thing the browser talks to
        |  session cookie is set here   |
        +------------------------------+
                       |  HTTPS, X-Proxy-Token, X-Forwarded-For: <browser>
                       v
        +------------------------------+
        |  Oracle Cloud VM (ARM)        |
        |    Caddy  - TLS, token gate   |
        |    uvicorn x2  - FastAPI      |
        |    celery worker              |
        |    celery beat                |
        +------------------------------+
              |            |          |
              v            v          v
          Neon         Upstash    Cloudflare R2
        PostgreSQL      Redis       storage
                                       |
                                    Resend
                                     email
```

The browser never addresses the API. It calls the Next.js server on its own
origin, which forwards to the API server-side. That is what keeps the session
cookie `Secure`, `HttpOnly` and first-party without any cross-origin
concessions — the constraint that shaped this whole layout.

### Why the API is not on Vercel

Celery beat has to run continuously and Celery workers have to outlive a
request. Vercel's functions are request-scoped, so the queue would have no
consumer. Splitting the API onto a small always-on VM keeps the worker and beat
as real long-lived processes, which is what the design assumes.

## The proxy boundary

The API trusts `X-Forwarded-For` to identify callers for rate limiting. Anything
that can reach the API directly could therefore forge an address and evade the
limits. Two mechanisms close that:

1. **uvicorn binds to loopback.** Only Caddy can reach it, and the VM's firewall
   opens 80 and 443 alone.
2. **A shared secret.** The Next.js server sends `X-Proxy-Token`; Caddy rejects
   requests without it, and the API checks it again itself
   ([middleware.py](../apps/api/src/serviceflow/api/middleware.py)) so the
   protection does not depend on the edge config being right. `/health` and
   `/ready` are exempt so uptime checks need no credential.

`TRUSTED_PROXY_COUNT=2` follows from the diagram. The frontend puts the browser
first in `X-Forwarded-For`; Caddy appends its own peer. The API sees
`[browser, vercel-egress]` and takes the entry two from the right. Setting this
to 1 would rate-limit Vercel's egress IP — meaning one abusive visitor would
lock out everyone. Setting it to 0 would key every caller on Caddy's loopback
address, collapsing all visitors into a single bucket.

## Database pool sizing

Three processes hold pools: two uvicorn workers and one Celery worker.

```
3 processes x (DATABASE_POOL_SIZE 5 + DATABASE_MAX_OVERFLOW 5) = 30 connections
```

Beat holds a connection only while a scheduled task runs, and migrations use a
short-lived one. Thirty is the ceiling to check against the provider's limit
before changing either number. Neon's free tier serves this comfortably through
its pooled endpoint; **use the `-pooler` connection string**, not the direct one.

`DATABASE_POOL_TIMEOUT=5` is deliberate. Phase 8 measured that the 30-second
default turned pool exhaustion into thread starvation — throughput collapsed to
2 requests/second because every worker sat waiting. At 5 seconds the API sheds
load instead: exhaustion surfaces as **503 with `Retry-After`**, not a generic
500, and that behavior must survive any pool retuning.

## Prerequisites you have to create

These need a human. Each is free at the tier used.

| Account | What for | What to note down |
| --- | --- | --- |
| Oracle Cloud | The API VM (Always Free ARM) | public IP, SSH key |
| Neon | PostgreSQL | pooled connection string |
| Upstash | Redis | `rediss://` URL |
| Cloudflare R2 | Photo storage | account id, access key, secret |
| Resend | Email | API key, a verified sending domain |
| Vercel | Frontend | project linked to the GitHub repo |
| A domain | `api.` for the VM, apex for the frontend | DNS control |

Two Oracle-specific warnings, verified against their current terms:

- **A credit card is required to create the account.** It is not charged while
  you stay on Always Free resources.
- **Capacity is regional and often unavailable.** "Out of host capacity" on
  Ampere A1 shapes is common; you may have to retry or pick another home region.
  The Always Free ARM allowance was reduced to 2 OCPU / 12 GB on 15 June 2026,
  which is still comfortably above this app's measured footprint of roughly
  250 MB RSS for the API, worker and beat together.
- Oracle may **stop idle instances** — under 10% CPU and network across 7 days.
  A public demo with little traffic can qualify. An external uptime check
  against `/health` mitigates but does not eliminate this; treat it as a real
  risk of a free tier rather than something the code can solve.

## Bringing up the VM

```bash
# On the instance, once.
scp -r deploy/oracle ubuntu@<vm-ip>:/tmp/
ssh ubuntu@<vm-ip> 'sudo bash /tmp/oracle/bootstrap.sh'
```

[bootstrap.sh](../deploy/oracle/bootstrap.sh) installs Caddy and uv, creates the
`serviceflow` service account, lays out `/opt/serviceflow` and
`/var/lib/serviceflow`, and opens ports 80 and 443. Oracle's images `REJECT` by
default in iptables *in addition to* the cloud-level security list, so both have
to be opened — a security-list rule alone leaves you locked out, which is the
single most common way this deployment appears broken.

Then, on the server:

```bash
sudo cp /tmp/oracle/api.env.example /etc/serviceflow/api.env
sudo nano /etc/serviceflow/api.env          # paste real values
# root writes it, the service account reads it, nobody else can.
sudo chown root:serviceflow /etc/serviceflow/api.env
sudo chmod 640 /etc/serviceflow/api.env
sudo cp /tmp/oracle/serviceflow-*.service /etc/systemd/system/
sudo cp /tmp/oracle/Caddyfile /etc/caddy/Caddyfile   # edit the hostname first
sudo systemctl daemon-reload
sudo systemctl enable --now serviceflow-api serviceflow-worker serviceflow-beat
sudo systemctl reload caddy
```

Caddy needs `API_PROXY_TOKEN` in its own environment for the token gate:

```bash
sudo systemctl edit caddy      # [Service] / Environment="API_PROXY_TOKEN=..."
```

### First run only

```bash
sudo -u serviceflow /opt/serviceflow/current/apps/api/.venv/bin/alembic upgrade head
```

Seeding is separate and manual **by design**. `deploy.sh` never seeds, and no
service unit does either: the seed writes synthetic demo records into whatever
database it is handed, so it must never be reachable from an automated path. It
is idempotent, so running it twice is harmless — but it will not clean anything
up either, and a genuine reset means dropping the database yourself. For a
portfolio demo, run it once, deliberately:

```bash
sudo -u serviceflow /opt/serviceflow/current/apps/api/.venv/bin/python -m serviceflow.db.seed
```

## Deploying a new version

```bash
sudo -u serviceflow -H SERVICEFLOW_REPO=git@github.com:you/serviceflow.git \
  /opt/serviceflow/deploy.sh <git-sha>
```

[deploy.sh](../deploy/oracle/deploy.sh) checks out into a timestamped release
directory, builds the venv with `uv sync --frozen --no-dev`, **runs migrations
before switching anything**, then moves the `current` symlink and restarts
worker, API and beat in that order. Five releases are kept, so a rollback is a
symlink change and three restarts.

The GitHub Actions workflow [deploy.yml](../.github/workflows/deploy.yml) does
exactly this over SSH. It stays inert until four secrets exist —
`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_REPO` — so the workflow
does not fail on every push before the infrastructure is real.

The frontend deploys itself: Vercel builds on push to `main`. Set these in the
Vercel project (all server-side, none are `NEXT_PUBLIC_`):

```
API_URL=https://api.your-domain.com
API_PROXY_TOKEN=<same value as the server>
```

## Verifying a deployment

```bash
curl https://api.your-domain.com/health     # {"status":"ok"}
curl https://api.your-domain.com/ready      # database + redis, 503 if either is down
curl https://api.your-domain.com/api/v1/bookings   # 403: no proxy token
./scripts/smoke.sh https://your-domain.com
```

[smoke.sh](../scripts/smoke.sh) signs in as all three demo roles and drives the
real workflow: books an appointment in a slot it finds free on the technician's
actual calendar, replays the request to prove idempotency, confirms it, works
the job, checks that an internal note never reaches the customer, that the
presigned upload is short-lived and points at the configured bucket, and that
the Celery worker actually drained the email outbox. It is the deployment's
acceptance test, and it fails loudly rather than skipping.

Run it against the **freshly deployed** frontend, not a local build — the
session cookie, the proxy hop and the storage host are exactly what it is
checking, and none of them exist locally.

## Logs

```bash
sudo journalctl -u serviceflow-api -f          # JSON, one object per line
sudo journalctl -u serviceflow-worker -f
sudo journalctl -u serviceflow-beat -f
sudo tail -f /var/log/caddy/serviceflow.log
```

Every API line carries the correlation id that the response returned in
`X-Request-ID`, so a user-reported failure can be traced from the browser to the
handler that produced it. At startup the API logs its deployment configuration
and warns about anything unsafe for production — `DEBUG` on, `PUBLIC_DEMO_MODE`,
a localhost CORS origin, `TRUSTED_PROXY_COUNT=0` behind a proxy, or SMTP still
configured instead of a real provider.

## Public demo mode

The dev auth provider issues its own tokens, which is not something a production
deployment should ever do silently. The API therefore **refuses to start** with
`AUTH_PROVIDER=dev` in production unless `PUBLIC_DEMO_MODE=true` is set
explicitly. That flag is the deliberate statement that this deployment's logins
are published on purpose. A real tenant deployment sets `AUTH_PROVIDER=clerk`
instead, and the flag stays off.
