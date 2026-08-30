import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real application: the Next.js server, the
 * FastAPI backend, PostgreSQL, Redis, MinIO and (where a flow needs it) the
 * Celery worker and MailPit. Nothing here is mocked - that is the point.
 *
 * Start the stack with `./scripts/e2e.sh`, which is also what runs this.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e/specs",
  // Serial by design, and the spec files are numbered so they run in story
  // order. The suite drives one seeded organization and hands work between
  // roles (a customer books, an admin confirms, an employee finishes); running
  // it in parallel would test the harness rather than the product.
  fullyParallel: false,
  workers: 1,
  // No retries: a flaky test is a bug to fix, not to paper over.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  globalSetup: "./e2e/support/global-setup.ts",
  globalTeardown: "./e2e/support/global-teardown.ts",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
