#!/usr/bin/env bash
# Smoke test for a freshly started Docker stack.
#
#   docker compose up --build -d && ./scripts/docker-smoke.sh
#
# Proves that a fresh environment can: run PostgreSQL, Redis, the API, the Celery
# worker and the web app; sign in as a demo user; create a customer; book them
# with a technician; read the booking back; work the job through to completion;
# keep another business out of all of it; and deliver the confirmation email
# through the worker to Mailpit. Every step prints; any failure exits non-zero.
set -euo pipefail

API="${API:-http://localhost:8000}"
WEB="${WEB:-http://localhost:3000}"
MAILPIT="${MAILPIT:-http://localhost:8025}"
PASSWORD="demo1234"
PASS=0
FAIL=0

say()  { printf '  %-62s %s\n' "$1" "$2"; }
ok()   { PASS=$((PASS + 1)); say "$1" "ok"; }
bad()  { FAIL=$((FAIL + 1)); say "$1" "FAILED ${2:-}"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {'d': d}))" "$1"; }

wait_for() { # url label
  for _ in $(seq 1 120); do
    curl -sf "$1" >/dev/null 2>&1 && { ok "$2"; return 0; }
    sleep 2
  done
  bad "$2" "(no answer from $1)"
  exit 1
}

token() { # email
  curl -sf -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$PASSWORD\"}" | json 'd["access_token"]'
}

call() { # token method path [body] -> body, with HTTP status on the last line
  local auth="$1" method="$2" path="$3" body="${4:-}"
  if [ -n "$body" ]; then
    curl -s -w '\n%{http_code}' -X "$method" "$API/api/v1$path" -H "Authorization: Bearer $auth" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -s -w '\n%{http_code}' -X "$method" "$API/api/v1$path" -H "Authorization: Bearer $auth"
  fi
}
status() { tail -n1 <<<"$1"; }
body()   { sed '$d' <<<"$1"; }

echo "ServiceFlow Docker smoke test"

# 1-5. Every service is up. /health reports PostgreSQL and Redis from inside the API.
wait_for "$API/health" "API answers /health"
health="$(curl -sf "$API/health")"
[ "$(json 'd["checks"]["database"]' <<<"$health")" = "ok" ] && ok "PostgreSQL reachable from the API" || bad "PostgreSQL reachable from the API"
[ "$(json 'd["checks"]["redis"]' <<<"$health")" = "ok" ] && ok "Redis reachable from the API" || bad "Redis reachable from the API"
wait_for "$WEB/login" "Next.js serves the sign-in page"
if command -v docker >/dev/null 2>&1 && docker compose ps --status running --services 2>/dev/null | grep -qx worker; then
  ok "Celery worker container running"
else
  say "Celery worker container running" "(not checked: no docker compose here)"
fi

# 6. Sign in: through the web app's own login route, then for API calls.
code="$(curl -s -o /dev/null -w '%{http_code}' -D /tmp/sf-smoke-headers -X POST "$WEB/api/auth/login" \
  -H 'Content-Type: application/json' -d "{\"email\":\"dispatcher@serviceflow.demo\",\"password\":\"$PASSWORD\"}")"
if [ "$code" = "200" ] && grep -qi '^set-cookie: sf_session=' /tmp/sf-smoke-headers; then
  ok "demo dispatcher signs in through the web app"
else
  bad "demo dispatcher signs in through the web app" "(HTTP $code)"
fi
DISPATCHER="$(token dispatcher@serviceflow.demo)"
TECHNICIAN="$(token employee@serviceflow.demo)"
RIVAL="$(token harbor.owner@serviceflow.demo)"
[ -n "$DISPATCHER" ] && [ -n "$TECHNICIAN" ] && [ -n "$RIVAL" ] && ok "API tokens for dispatcher, technician and another tenant's owner" || bad "API tokens"

# 7. Create a customer.
RUN="$(date +%s)"
CUSTOMER_EMAIL="smoke.$RUN@example.com"
response="$(call "$DISPATCHER" POST /customers "{\"email\":\"$CUSTOMER_EMAIL\",\"first_name\":\"Smoke\",\"last_name\":\"Test $RUN\",\"address\":\"1 Test Lane, Evanston, IL 60201\"}")"
[ "$(status "$response")" = "201" ] && ok "create a customer" || bad "create a customer" "($(status "$response"))"
CUSTOMER_ID="$(body "$response" | json 'd["data"]["id"]')"

# 8. Book them with Alex Morgan at a slot the scheduling API says is free.
EMPLOYEE_ID="$(body "$(call "$DISPATCHER" GET '/employees?q=Alex&page_size=5')" | json '[e for e in d["data"] if e["user"]["email"]=="employee@serviceflow.demo"][0]["id"]')"
SERVICE_ID="$(body "$(call "$DISPATCHER" GET '/services?q=HVAC%20Inspection')" | json 'd["data"][0]["id"]')"
BOOKING_ID=""
for day in $(seq 3 21); do
  for hour in 14 16 18 20; do
    start="$(python3 -c "import datetime as d; t=d.datetime.now(d.UTC).replace(hour=$hour,minute=0,second=0,microsecond=0)+d.timedelta(days=$day); print(t.isoformat())")"
    free="$(body "$(call "$DISPATCHER" GET "/scheduling/candidates?service_id=$SERVICE_ID&start=${start/+/%2B}")" \
      | json "any(c['id']=='$EMPLOYEE_ID' and c['assignable'] for c in d['data'])")"
    if [ "$free" = "True" ]; then
      response="$(call "$DISPATCHER" POST /bookings "{\"customer_id\":\"$CUSTOMER_ID\",\"service_id\":\"$SERVICE_ID\",\"employee_id\":\"$EMPLOYEE_ID\",\"requested_start\":\"$start\"}")"
      if [ "$(status "$response")" = "201" ]; then
        BOOKING_ID="$(body "$response" | json 'd["data"]["id"]')"
        JOB_ID="$(body "$response" | json 'd["data"]["job"]["id"]')"
        break 2
      fi
    fi
  done
done
[ -n "$BOOKING_ID" ] && ok "book the customer with a technician (confirmed, job scheduled)" || { bad "book the customer with a technician"; exit 1; }

# 9. Read it back.
response="$(call "$DISPATCHER" GET "/bookings/$BOOKING_ID")"
[ "$(status "$response")" = "200" ] && [ "$(body "$response" | json 'd["data"]["status"]')" = "CONFIRMED" ] \
  && ok "retrieve the booking" || bad "retrieve the booking"

# A second booking for the same technician at the same time must be refused.
response="$(call "$DISPATCHER" POST /bookings "{\"customer_id\":\"$CUSTOMER_ID\",\"service_id\":\"$SERVICE_ID\",\"employee_id\":\"$EMPLOYEE_ID\",\"requested_start\":\"$start\"}")"
[ "$(status "$response")" = "409" ] && ok "a conflicting booking is refused with 409" || bad "a conflicting booking is refused" "($(status "$response"))"

# 10. The technician works the job through to completion.
[ "$(status "$(call "$TECHNICIAN" PATCH "/jobs/$JOB_ID" '{"status":"IN_PROGRESS"}')")" = "200" ] && ok "technician starts the job" || bad "technician starts the job"
response="$(call "$TECHNICIAN" PATCH "/jobs/$JOB_ID" '{"status":"COMPLETED","internal_notes":"Smoke test visit."}')"
[ "$(status "$response")" = "200" ] && [ "$(body "$response" | json 'd["data"]["status"]')" = "COMPLETED" ] \
  && ok "technician completes the job" || bad "technician completes the job"

# 11. Another business sees none of it.
[ "$(status "$(call "$RIVAL" GET "/bookings/$BOOKING_ID")")" = "404" ] && ok "another tenant cannot read the booking (404)" || bad "another tenant cannot read the booking"
[ "$(status "$(call "$RIVAL" GET "/customers/$CUSTOMER_ID")")" = "404" ] && ok "another tenant cannot read the customer (404)" || bad "another tenant cannot read the customer"
[ "$(status "$(call "$RIVAL" PATCH "/jobs/$JOB_ID" '{"status":"CANCELLED"}')")" = "404" ] && ok "another tenant cannot change the job (404)" || bad "another tenant cannot change the job"

# The worker delivered the confirmation email to Mailpit.
delivered=""
for _ in $(seq 1 45); do
  if curl -sf "$MAILPIT/api/v1/search?query=to:$CUSTOMER_EMAIL" | json 'd["messages_count"]' 2>/dev/null | grep -qv '^0$'; then
    delivered=yes; break
  fi
  sleep 2
done
[ -n "$delivered" ] && ok "Celery worker delivered the confirmation email (Mailpit)" || bad "Celery worker delivered the confirmation email"

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
