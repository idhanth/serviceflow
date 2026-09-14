/** Shared addresses and accounts. Everything points at the real running stack. */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

/** Seeded demo logins (local demo data only). */
export const DEMO_PASSWORD = "demo1234";

export const ACCOUNTS = {
  owner: "owner@serviceflow.demo",
  dispatcher: "dispatcher@serviceflow.demo",
  technician: "employee@serviceflow.demo",
  customer: "customer@serviceflow.demo",
  analyst: "analyst@serviceflow.demo",
  platform: "admin@serviceflow.demo",
  /** The owner of a different business, for tenant isolation. */
  rival: "harbor.owner@serviceflow.demo",
} as const;

export type Role = keyof typeof ACCOUNTS;

/** Where global setup parks each signed-in browser state. */
export const storageFor = (role: Role) => `e2e/.auth/${role}.json`;

/** Records created by one spec and used by a later one, in run order. */
export const RUN_STATE = "e2e/.auth/run.json";
