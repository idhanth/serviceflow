/** Shared addresses and accounts. Everything points at the real local stack. */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";
export const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? "http://127.0.0.1:8025";

/** Seeded demo logins (see the seed and the README). */
export const DEMO_PASSWORD = "demo1234";
export const ADMIN = { email: "admin@serviceflow.demo", password: DEMO_PASSWORD };
export const EMPLOYEE = { email: "employee@serviceflow.demo", password: DEMO_PASSWORD };
export const DEMO_CUSTOMER = { email: "customer@serviceflow.demo", password: DEMO_PASSWORD };

export const ORGANIZATION_SLUG = process.env.E2E_ORG_SLUG ?? "gleam-auto-detailing";

/** Where global setup parks the signed-in browser states. */
export const STORAGE = {
  admin: "e2e/.auth/admin.json",
  employee: "e2e/.auth/employee.json",
  /** The customer signed up for this run. */
  customer: "e2e/.auth/customer.json",
  /** The seeded demo customer, used to prove isolation between customers. */
  otherCustomer: "e2e/.auth/other-customer.json",
} as const;

export type Role = keyof typeof STORAGE;

/** The customer created for this run; global setup writes it here. */
export const RUN_STATE = "e2e/.auth/run.json";
