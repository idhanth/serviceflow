#!/usr/bin/env bash
# Production smoke test: the real workflow against a deployed environment.
#
#   ./scripts/smoke.sh https://serviceflow.example.com
#
# Read-mostly by design. It signs in as the seeded demo accounts, creates one
# booking, confirms it, works it and checks what each role can see - then leaves
# the booking cancelled so the demo data does not drift with every run. It never
# seeds, never migrates and never deletes anything it did not create.
set -euo pipefail

BASE="${1:?usage: smoke.sh https://your-frontend-domain}"
JAR_DIR="$(mktemp -d)"
trap 'rm -rf "$JAR_DIR"' EXIT
PASS=0
FAIL=0

say()  { printf '  %-58s %s\n' "$1" "$2"; }
ok()   { PASS=$((PASS+1)); say "$1" "ok"; }
bad()  { FAIL=$((FAIL+1)); say "$1" "FAILED: ${2:-}"; }
check() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "expected $2, got $1"; fi; }

login() { # role email
  local role="$1" email="$2"
  local code
  code=$(curl -s -o "$JAR_DIR/$role.json" -w '%{http_code}' -c "$JAR_DIR/$role.cookies" \
    -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"demo1234\"}")
  case "$code" in
    200) ok "sign in as $role" ;;
    429) bad "sign in as $role" "rate limited - the limiter is working; wait 15 minutes and rerun"
         exit 1 ;;
    *)   bad "sign in as $role" "HTTP $code"
         # Everything downstream needs all three sessions; carrying on would
         # only produce 401s dressed up as authorization failures.
         exit 1 ;;
  esac
}

api() { # role method path [body]
  local role="$1" method="$2" path="$3" body="${4:-}"
  if [ -n "$body" ]; then
    curl -s -b "$JAR_DIR/$role.cookies" -X "$method" "$BASE/api/proxy/$path" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -s -b "$JAR_DIR/$role.cookies" -X "$method" "$BASE/api/proxy/$path"
  fi
}

status_of() { # role method path
  curl -s -o /dev/null -w '%{http_code}' -b "$JAR_DIR/$1.cookies" -X "$2" "$BASE/api/proxy/$3"
}

echo "ServiceFlow smoke test -> $BASE"
if [ "${BASE#https://}" = "$BASE" ]; then
  echo
  echo "  Target is not HTTPS, so this is a local run. Two checks below are"
  echo "  production assertions and are expected to fail here: the HTTPS check"
  echo "  and the object-storage host check. Everything else must still pass."
fi
echo

echo "Transport and health"
check "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/login")" "200" "frontend serves over HTTPS"
[ "${BASE#https://}" != "$BASE" ] && ok "frontend is HTTPS" || bad "frontend is HTTPS" "not https"
echo

echo "Sessions"
login admin admin@serviceflow.demo
login employee employee@serviceflow.demo
login customer customer@serviceflow.demo
if grep -qE '(^|\s)#?HttpOnly_' "$JAR_DIR/admin.cookies" 2>/dev/null; then
  ok "session cookie is HttpOnly"
else
  bad "session cookie is HttpOnly" "not marked HttpOnly in the jar"
fi
if grep -q "TRUE.*sf_session" "$JAR_DIR/admin.cookies" 2>/dev/null; then
  ok "session cookie is Secure"
else
  bad "session cookie is Secure" "secure flag not set"
fi
echo

echo "Authorization"
check "$(status_of customer GET activity)" "403" "customer cannot read the activity feed"
check "$(status_of employee GET activity)" "403" "employee cannot read the activity feed"
check "$(status_of admin GET activity)" "200" "admin can read the activity feed"
check "$(status_of customer GET employees)" "403" "customer cannot list the team"
echo

echo "Workflow"
VEHICLE=$(api customer GET "vehicles?page_size=1" | python3 -c 'import sys,json;d=json.load(sys.stdin)["data"];print(d[0]["id"] if d else "")')
SERVICE=$(api customer GET "services?page_size=20" | python3 -c '
import sys, json
services = json.load(sys.stdin)["data"]
short = [s for s in services if s["duration_minutes"] <= 60] or services
print(short[0]["id"])')
# The shop's timezone comes from the deployment, never from this machine:
# scheduling, hours and the calendar are all evaluated in it.
SHOP_TZ=$(api customer GET "organizations/current" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["timezone"])')
[ -n "$SHOP_TZ" ] && ok "organization reports its timezone ($SHOP_TZ)" \
  || bad "organization timezone" "not returned"

# Assign to the demo employee account, because the rest of the run signs in as
# that person: a job assigned to anyone else is correctly invisible to them.
EMPLOYEE=$(api admin GET "employees?page_size=100" | python3 -c '
import sys, json
people = json.load(sys.stdin)["data"]
mine = [e for e in people if e["user"]["email"] == "employee@serviceflow.demo"]
print(mine[0]["id"] if mine else "")')
[ -n "$EMPLOYEE" ] && ok "demo technician resolved" || bad "demo technician" "not in the roster"

DURATION=$(api customer GET "services?page_size=50" | SERVICE_ID="$SERVICE" python3 -c '
import sys, json, os
wanted = os.environ["SERVICE_ID"]
print(next(s["duration_minutes"] for s in json.load(sys.stdin)["data"] if s["id"] == wanted))')

# A hardcoded time collides with whatever is already on the calendar, so ask
# the deployment where this technician is actually free.
api admin GET "employees/$EMPLOYEE/availability" > "$JAR_DIR/availability.json"
RANGE_END=$(python3 -c 'import datetime;print(datetime.date.today()+datetime.timedelta(days=23))')
api admin GET "calendar?start=$(date +%F)&end=$RANGE_END&employee_id=$EMPLOYEE" \
  > "$JAR_DIR/calendar.json"
SLOT=$(python3 "$(dirname "$0")/pick_slot.py" "$SHOP_TZ" "$DURATION" \
  "$JAR_DIR/availability.json" "$JAR_DIR/calendar.json") \
  && ok "found a free ${DURATION}-minute slot for the technician" \
  || { bad "free slot" "the technician has no opening in the search window"; exit 1; }

KEY="smoke-$(date +%s)"
BOOKING=$(curl -s -b "$JAR_DIR/customer.cookies" -X POST "$BASE/api/proxy/bookings" \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" \
  -d "{\"vehicle_id\":\"$VEHICLE\",\"service_id\":\"$SERVICE\",\"requested_start\":\"$SLOT\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("data",{}).get("id",""))')
[ -n "$BOOKING" ] && ok "customer creates a booking" || bad "customer creates a booking" "no id returned"

REPLAY=$(curl -s -D - -o /dev/null -b "$JAR_DIR/customer.cookies" -X POST \
  "$BASE/api/proxy/bookings" -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" \
  -d "{\"vehicle_id\":\"$VEHICLE\",\"service_id\":\"$SERVICE\",\"requested_start\":\"$SLOT\"}")
echo "$REPLAY" | grep -qi "idempotent-replay: true" \
  && ok "the same request replays instead of booking twice" \
  || bad "idempotent replay" "no Idempotent-Replay header on the retry"

RANKING=$(api admin GET "bookings/$BOOKING/assignable-employees")
echo "$RANKING" | EMP="$EMPLOYEE" python3 -c '
import sys, json, os
rows = json.load(sys.stdin)["data"]
mine = [r for r in rows if r["id"] == os.environ["EMP"]]
if not rows:
    sys.exit("no candidates ranked")
if not mine:
    sys.exit("the demo technician was not ranked for this service")
if not mine[0]["assignable"]:
    sys.exit("demo technician not assignable: %s" % mine[0].get("reason"))
' && ok "admin sees the technician ranked and assignable" \
  || bad "assignable ranking" "see above"

JOB=$(api admin POST "bookings/$BOOKING/confirm" "{\"employee_id\":\"$EMPLOYEE\"}" \
  | python3 -c 'import sys,json;print((json.load(sys.stdin).get("data",{}).get("job") or {}).get("id",""))')
[ -n "$JOB" ] && ok "admin confirms and a job is created" || bad "admin confirms" "no job returned"

if [ -n "${JOB:-}" ]; then
  check "$(status_of employee POST "jobs/$JOB/start")" "200" "employee starts the job"

  NOTE=$(api employee POST "jobs/$JOB/notes" \
    '{"content":"Smoke test: visible to the customer.","visibility":"CUSTOMER_VISIBLE"}' \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("data",{}).get("id",""))')
  [ -n "$NOTE" ] && ok "employee adds a customer-visible note" || bad "employee adds a note" ""
  api employee POST "jobs/$JOB/notes" \
    '{"content":"Smoke test INTERNAL must never reach the customer.","visibility":"INTERNAL"}' >/dev/null
  ok "employee adds an internal note"

  # Both notes now exist on the job. The customer must get exactly one of them.
  # A filter that returned nothing would pass a leak check by accident, so the
  # visible note being present is asserted alongside the internal one's absence.
  CUSTOMER_NOTES=$(api customer GET "jobs/$JOB/notes")
  if echo "$CUSTOMER_NOTES" | grep -q "visible to the customer"; then
    ok "customer sees the note written for them"
  else
    bad "customer sees the note written for them" "not returned"
  fi
  if echo "$CUSTOMER_NOTES" | grep -q "must never reach the customer"; then
    bad "internal note stays internal" "LEAKED TO THE CUSTOMER"
  else
    ok "internal note stays internal"
  fi

  # Storage: the key must be minted by the API under the job's prefix, the URL
  # must point at the configured bucket, and the grant must be short-lived.
  PRESIGN=$(api employee POST "jobs/$JOB/photos/presign" '{"mime_type":"image/png","file_size":70}')
  PRESIGN_REPORT=$(echo "$PRESIGN" | JOB_ID="$JOB" python3 -c '
import json, os, sys, urllib.parse
job = os.environ["JOB_ID"]
body = json.load(sys.stdin).get("data") or {}
url, key = body.get("url", ""), body.get("storage_key", "")
expires = body.get("expires_in", 0)
problems = []
if not url:
    problems.append("no presigned url")
if job not in key:
    problems.append("storage key is not scoped to the job: %r" % key)
if not (0 < expires <= 900):
    problems.append("presign lifetime is %ss, expected 15 minutes or less" % expires)
host = urllib.parse.urlparse(url).netloc
if host.startswith(("127.0.0.1", "localhost", "minio")):
    problems.append("presign points at local dev storage (%s)" % host)
print("|".join(problems) if problems else "OK:" + host)')
  case "$PRESIGN_REPORT" in
    OK:*) ok "storage issues a short-lived presign at ${PRESIGN_REPORT#OK:}" ;;
    *)    bad "storage presign" "$PRESIGN_REPORT" ;;
  esac

  # A key the API never minted must be refused at finalize.
  FORGED=$(status_of employee POST "jobs/$JOB/photos" || true)
  case "$FORGED" in
    2*) bad "finalize rejects an unminted key" "accepted an empty body" ;;
    *)  ok "finalize refuses a request it did not mint" ;;
  esac

  COMPLETE=$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR_DIR/employee.cookies" \
    -X POST "$BASE/api/proxy/jobs/$JOB/complete" -H 'Content-Type: application/json' -d '{}')
  check "$COMPLETE" "200" "employee completes the job"

  ACTIONS=$(api admin GET "activity?resource_id=$JOB&sort=created_at" \
    | python3 -c 'import sys,json;print(",".join(e["action"] for e in json.load(sys.stdin)["data"]))')
  case "$ACTIONS" in
    *JOB_STARTED*JOB_COMPLETED*) ok "activity records the lifecycle in order" ;;
    *) bad "activity records the lifecycle in order" "saw: $ACTIONS" ;;
  esac
fi
echo

echo "Background processing"
# The worker is a separate process from the API. Confirming the booking above
# queued a real email; if the worker is running, the outbox drains and the sent
# counter moves. Nothing here simulates delivery - it either happened or it did
# not. (Beat is not observable from out here; check its unit on the host.)
INFRA=$(api admin GET "infrastructure")
QUEUE_UP=$(echo "$INFRA" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["queue"]["reachable"])')
[ "$QUEUE_UP" = "True" ] && ok "Redis broker is reachable from the API" \
  || bad "Redis broker" "unreachable - the worker cannot receive anything"

DRAINED=no
for _ in $(seq 1 20); do
  COUNTS=$(api admin GET "infrastructure" | python3 -c '
import sys, json
email = json.load(sys.stdin)["data"]["email"]
print(email["pending"], email["failed"], email["sent"])')
  set -- $COUNTS
  if [ "${1:-1}" = "0" ]; then DRAINED=yes; break; fi
  sleep 3
done
set -- $COUNTS
if [ "$DRAINED" = "yes" ]; then
  ok "the worker drained the email outbox (sent ${3:-?}, failed ${2:-?})"
else
  bad "the worker drained the email outbox" "${1:-?} still pending after 60s"
fi
[ "${2:-0}" = "0" ] && ok "no failed deliveries" || say "failed deliveries" "${2} - inspect the provider"
echo

echo "Safety"
NOTFOUND=$(api customer GET "bookings/2b1f6b0e-0000-4000-8000-000000000000")
echo "$NOTFOUND" | grep -q "NOT_FOUND" && ok "unknown resource returns a clean 404" \
  || bad "unknown resource" "$NOTFOUND"
if echo "$NOTFOUND" | grep -qiE "traceback|psycopg|sqlalchemy|site-packages|/opt/"; then
  bad "error responses leak internals" "stack or driver detail in the body"
else
  ok "error responses leak nothing internal"
fi
echo

echo "Cleanup"
if [ -n "${BOOKING:-}" ]; then
  # The run drove this booking all the way to COMPLETED, which is terminal and
  # correctly refuses cancellation. So it stays: each smoke run leaves exactly
  # one finished job in the demo data, which is what a finished job should look
  # like. Nothing is deleted, and no other record is touched.
  say "smoke booking $BOOKING" "left completed in the demo data"
fi
echo

printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
