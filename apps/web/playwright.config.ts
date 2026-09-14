import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real application: the Next.js server, the
 * FastAPI backend, PostgreSQL, Redis, MinIO and (where a flow needs it) the
 * Celery worker and MailPit. Nothing here is mocked - that is the point.
 *
 * Start the stack first (`docker compose up --build -d`), then `npx playwright test`.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e/specs",
  // Serial by design, and the spec files are numbered so they run in story
  // order: a dispatcher books, the technician finishes the job, other roles and
  // another business then try to reach it.
  fullyParallel: false,
  workers: 1,
  // No retries: a flaky test is a bug to fix, not to paper over.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  globalSetup: "./e2e/support/global-setup.ts",
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
