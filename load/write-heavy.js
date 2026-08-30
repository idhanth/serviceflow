import http from "k6/http";

import { BASE, auth, bookingContext, bookingPayload, idempotencyKey, ok } from "./lib.js";

/**
 * Booking creation under load, every request carrying its own idempotency key -
 * which is what a real client does, and what makes the post-run invariant
 * check meaningful: no key may have produced two bookings.
 */
export const options = {
  // p99 is not in k6's default summary, and a load report without it hides the
  // tail that users actually feel.
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: {
    writes: {
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
  const response = http.post(
    `${BASE}/api/v1/bookings`,
    bookingPayload(context.vehicleId, context.serviceId),
    {
      ...auth(context.customer, {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey("load"),
      }),
      tags: { name: "create booking" },
    },
  );
  ok(response, "create booking");
}
