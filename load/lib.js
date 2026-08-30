import http from "k6/http";
import { check, fail } from "k6";

export const BASE = __ENV.LOAD_API_URL || "http://127.0.0.1:8100";
export const PASSWORD = "demo1234";

/**
 * Signs a user in once and returns the bearer token.
 *
 * Called from setup(), never per iteration: the point of the run is to measure
 * the endpoints under test, and a login on every iteration would measure
 * password hashing instead.
 */
export function login(email) {
  const response = http.post(
    `${BASE}/api/v1/auth/login`,
    JSON.stringify({ email, password: PASSWORD }),
    { headers: { "Content-Type": "application/json" }, tags: { name: "login" } },
  );
  if (response.status !== 200) {
    fail(`login for ${email} failed with ${response.status}: ${response.body}`);
  }
  return response.json("access_token");
}

export function auth(token, extra) {
  return { headers: { Authorization: `Bearer ${token}`, ...(extra || {}) } };
}

/** The context a write scenario needs: who to book as, and what to book. */
export function bookingContext() {
  const customer = login("customer@serviceflow.demo");
  const vehicles = http.get(`${BASE}/api/v1/vehicles?page_size=5`, auth(customer));
  const services = http.get(`${BASE}/api/v1/services?page_size=10`, auth(customer));
  if (vehicles.status !== 200 || services.status !== 200) {
    fail(`could not read the catalogue: ${vehicles.status}/${services.status}`);
  }
  const service = services
    .json("data")
    .find((item) => item.duration_minutes <= 60) || services.json("data")[0];

  return {
    admin: login("admin@serviceflow.demo"),
    customer,
    vehicleId: vehicles.json("data")[0].id,
    serviceId: service.id,
  };
}

/**
 * A booking request far enough out to be valid, spread across a wide window so
 * the run is not just one employee's calendar colliding with itself.
 */
export function bookingPayload(vehicleId, serviceId) {
  const daysAhead = 60 + Math.floor(Math.random() * 300);
  const when = new Date(Date.now() + daysAhead * 86400000);
  when.setUTCHours(18, 0, 0, 0);
  return JSON.stringify({
    vehicle_id: vehicleId,
    service_id: serviceId,
    requested_start: when.toISOString(),
  });
}

/** A key unique to this virtual user and iteration, as a real client would send. */
export function idempotencyKey(prefix) {
  return `${prefix}-${__VU}-${__ITER}-${Date.now()}`;
}

export function ok(response, name) {
  return check(response, { [`${name} succeeded`]: (r) => r.status >= 200 && r.status < 300 });
}
