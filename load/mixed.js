import { sleep } from "k6";
import http from "k6/http";

import { BASE, auth, bookingContext, bookingPayload, idempotencyKey, ok } from "./lib.js";

/**
 * The realistic shape: mostly reads, some search, a booking now and then, and
 * the occasional retry of a booking that was already sent - which must replay
 * rather than duplicate.
 */
export const options = {
  // p99 is not in k6's default summary, and a load report without it hides the
  // tail that users actually feel.
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: {
    mixed: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 100),
      duration: __ENV.DURATION || "60s",
    },
  },
  thresholds: { http_req_failed: ["rate<0.05"] },
};

export function setup() {
  return bookingContext();
}

export default function (context) {
  const admin = auth(context.admin);
  const customer = auth(context.customer);

  ok(http.get(`${BASE}/api/v1/bookings?page_size=20`, { ...admin, tags: { name: "bookings" } }), "bookings");
  ok(http.get(`${BASE}/api/v1/jobs?page_size=20`, { ...admin, tags: { name: "jobs" } }), "jobs");

  if (__ITER % 3 === 0) {
    ok(http.get(`${BASE}/api/v1/search?q=detail`, { ...admin, tags: { name: "search" } }), "search");
  }

  if (__ITER % 5 === 0) {
    const key = idempotencyKey("mixed");
    const payload = bookingPayload(context.vehicleId, context.serviceId);
    const headers = auth(context.customer, {
      "Content-Type": "application/json",
      "Idempotency-Key": key,
    });

    const created = http.post(`${BASE}/api/v1/bookings`, payload, {
      ...headers,
      tags: { name: "create booking" },
    });
    ok(created, "create booking");

    // The same request again, exactly as an impatient client would resend it.
    const retry = http.post(`${BASE}/api/v1/bookings`, payload, {
      ...headers,
      tags: { name: "retry booking" },
    });
    ok(retry, "retry booking");
  }

  ok(
    http.get(`${BASE}/api/v1/bookings?page_size=10`, { ...customer, tags: { name: "my bookings" } }),
    "my bookings",
  );
  sleep(0.1);
}
