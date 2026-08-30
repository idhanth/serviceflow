import { sleep } from "k6";
import http from "k6/http";

import { BASE, auth, login, ok } from "./lib.js";

/**
 * The reads a busy shop actually does: an admin watching queues and the
 * calendar, a customer checking their bookings, and search.
 */
export const options = {
  // p99 is not in k6's default summary, and a load report without it hides the
  // tail that users actually feel.
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: {
    steady: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 100),
      duration: __ENV.DURATION || "60s",
    },
  },
  thresholds: {
    // Recorded, not enforced as a pass mark: the number this machine produces
    // is the finding, and inventing a target would be inventing a result.
    http_req_failed: ["rate<0.05"],
  },
};

export function setup() {
  return { admin: login("admin@serviceflow.demo"), customer: login("customer@serviceflow.demo") };
}

export default function (tokens) {
  const admin = auth(tokens.admin);
  const customer = auth(tokens.customer);

  ok(http.get(`${BASE}/api/v1/bookings?page_size=20`, { ...admin, tags: { name: "bookings" } }), "bookings");
  ok(http.get(`${BASE}/api/v1/customers?page_size=20`, { ...admin, tags: { name: "customers" } }), "customers");
  ok(http.get(`${BASE}/api/v1/services?page_size=20`, { ...customer, tags: { name: "services" } }), "services");

  const start = new Date();
  const end = new Date(Date.now() + 7 * 86400000);
  ok(
    http.get(
      `${BASE}/api/v1/calendar?start=${start.toISOString().slice(0, 10)}&end=${end
        .toISOString()
        .slice(0, 10)}`,
      { ...admin, tags: { name: "calendar" } },
    ),
    "calendar",
  );
  ok(http.get(`${BASE}/api/v1/search?q=santos`, { ...admin, tags: { name: "search" } }), "search");
  ok(
    http.get(`${BASE}/api/v1/bookings?page_size=10`, { ...customer, tags: { name: "my bookings" } }),
    "my bookings",
  );

  sleep(0.1);
}
