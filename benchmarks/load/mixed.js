import http from "k6/http";
import { check, fail } from "k6";
import { SharedArray } from "k6/data";

/**
 * The realistic mix: authenticated staff working across 25 businesses.
 *
 *   GET   /bookings    25%     PATCH /jobs      10%
 *   GET   /jobs        20%     POST  /bookings  10%
 *   GET   /customers   15%     GET   /dashboard  5%
 *   GET   /schedule    15%
 *
 * Each virtual user signs in once as its tenant's dispatcher (in setup, so the
 * run measures the endpoints, not password hashing) and stays in that tenant.
 *
 * Writes are built so that a correct server never has a reason to refuse them:
 * every new booking has a start no other request uses, and every job update is
 * a legal transition on a job only this virtual user touches. So any 4xx or 5xx
 * is counted as the failure it is - nothing here is marked "expected".
 */

const BASE = __ENV.LOAD_API_URL || "http://127.0.0.1:8100";
const manifest = JSON.parse(open(__ENV.DATASET_MANIFEST || "./.dataset.json"));
const tenants = new SharedArray("tenants", () => manifest.tenants);

export const options = {
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: {
    mixed: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 100),
      duration: __ENV.DURATION || "60s",
      gracefulStop: "10s",
    },
  },
  setupTimeout: "180s",
  // Never-failing thresholds on each endpoint's tag: k6 only exports tagged
  // sub-metrics that a threshold references, and the report needs them.
  thresholds: {
    http_req_failed: ["rate<1"],
    "http_req_duration{name:GET /bookings}": ["max>=0"],
    "http_req_duration{name:GET /jobs}": ["max>=0"],
    "http_req_duration{name:GET /customers}": ["max>=0"],
    "http_req_duration{name:GET /schedule}": ["max>=0"],
    "http_req_duration{name:POST /bookings}": ["max>=0"],
    "http_req_duration{name:PATCH /jobs}": ["max>=0"],
    "http_req_duration{name:GET /dashboard}": ["max>=0"],
  },
};

function login(email) {
  const response = http.post(
    `${BASE}/api/v1/auth/login`,
    JSON.stringify({ email, password: manifest.password }),
    { headers: { "Content-Type": "application/json" }, tags: { name: "login" } },
  );
  if (response.status !== 200) fail(`login ${email}: ${response.status} ${response.body}`);
  return response.json("access_token");
}

export function setup() {
  const sessions = [];
  for (const tenant of manifest.tenants) {
    const token = login(tenant.accounts.dispatcher);
    const headers = { Authorization: `Bearer ${token}` };
    const pick = (path) => {
      const response = http.get(`${BASE}/api/v1/${path}`, { headers, tags: { name: "setup" } });
      if (response.status !== 200) fail(`setup ${path}: ${response.status}`);
      return response.json("data");
    };
    const customers = pick("customers?page_size=100").map((row) => row.id);
    const services = pick("services?page_size=20").map((row) => ({ id: row.id, minutes: row.duration_minutes }));
    const employees = pick("employees?page_size=100").map((row) => row.id);
    // A pool of scheduled jobs to move along. Each VU gets its own slice.
    const jobs = [];
    for (let page = 1; page <= 6; page += 1) {
      for (const row of pick(`jobs?status=SCHEDULED&timeframe=upcoming&page_size=100&page=${page}`)) jobs.push(row.id);
    }
    sessions.push({ token, customers, services, employees, jobs });
  }
  return { sessions, startedAt: Date.now() };
}

// Per-VU state (k6 gives every VU its own copy of module scope).
const DEBUG_FAILURES = __ENV.DEBUG_FAILURES === "1";
let reportedFailures = 0;

/** With DEBUG_FAILURES=1, print the first few failing responses so a run explains itself. */
function explain(response, name) {
  if (DEBUG_FAILURES && response.status >= 400 && reportedFailures < 8) {
    reportedFailures += 1;
    console.warn(`${name} -> ${response.status} ${String(response.body).slice(0, 240)}`);
  }
}

let jobCursor = 0;
let jobStep = 0;
let bookingCounter = 0;

function get(session, path, name) {
  const response = http.get(`${BASE}/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${session.token}` },
    tags: { name },
  });
  check(response, { [`${name} 200`]: (r) => r.status === 200 });
  explain(response, name);
  return response;
}

function isoDay(offsetDays) {
  return new Date(Date.now() + offsetDays * 86400000).toISOString().slice(0, 10);
}

export default function (data) {
  const tenantIndex = (__VU - 1) % data.sessions.length;
  const session = data.sessions[tenantIndex];
  const roll = Math.random() * 100;

  if (roll < 25) {
    const page = 1 + Math.floor(Math.random() * 5);
    const filters = ["", "&status=CONFIRMED", "&timeframe=upcoming", "&status=PENDING"][page % 4];
    get(session, `bookings?page=${page}&page_size=25${filters}`, "GET /bookings");
  } else if (roll < 45) {
    const filters = ["&status=SCHEDULED&timeframe=upcoming", "&status=COMPLETED", "", "&status=NEW&timeframe=upcoming"][__ITER % 4];
    get(session, `jobs?page=${1 + Math.floor(Math.random() * 3)}&page_size=25${filters}`, "GET /jobs");
  } else if (roll < 60) {
    const page = 1 + Math.floor(Math.random() * 15);
    get(session, `customers?page=${page}&page_size=25`, "GET /customers");
  } else if (roll < 75) {
    const day = isoDay(Math.floor(Math.random() * 14) - 7);
    get(session, `schedule?start=${day}`, "GET /schedule");
  } else if (roll < 85) {
    // A start no other request will ever use: this VU, this booking, its own minute.
    bookingCounter += 1;
    // Each VU owns a two-day band of minutes starting a month out, so no two
    // requests share a start and every start stays inside the one-year window.
    const minutesAhead = 60 * 24 * 30 + __VU * 2880 + bookingCounter;
    const start = new Date(data.startedAt + minutesAhead * 60000);
    start.setUTCSeconds(0, 0);
    const service = session.services[bookingCounter % session.services.length];
    const response = http.post(
      `${BASE}/api/v1/bookings`,
      JSON.stringify({
        customer_id: session.customers[(__VU + bookingCounter) % session.customers.length],
        service_id: service.id,
        requested_start: start.toISOString(),
      }),
      {
        headers: { Authorization: `Bearer ${session.token}`, "Content-Type": "application/json" },
        tags: { name: "POST /bookings" },
      },
    );
    check(response, { "POST /bookings 201": (r) => r.status === 201 });
    explain(response, "POST /bookings");
  } else if (roll < 95) {
    // Walk this VU's own slice of the scheduled jobs: start one, then complete it.
    const vusInTenant = Math.max(1, Math.ceil(Number(__ENV.VUS || 100) / data.sessions.length));
    const slice = Math.max(1, Math.floor(session.jobs.length / vusInTenant));
    const offset = Math.floor((__VU - 1) / data.sessions.length) * slice;
    const jobId = session.jobs[(offset + (jobCursor % slice)) % session.jobs.length];
    const body = jobStep === 0 ? { status: "IN_PROGRESS" } : { status: "COMPLETED", internal_notes: "Load test visit." };
    const response = http.patch(`${BASE}/api/v1/jobs/${jobId}`, JSON.stringify(body), {
      headers: { Authorization: `Bearer ${session.token}`, "Content-Type": "application/json" },
      tags: { name: "PATCH /jobs" },
    });
    check(response, { "PATCH /jobs 200": (r) => r.status === 200 });
    explain(response, `PATCH /jobs ${JSON.stringify(body)}`);
    if (jobStep === 1) jobCursor += 1;
    jobStep = 1 - jobStep;
  } else {
    get(session, "dashboard", "GET /dashboard");
  }
}
