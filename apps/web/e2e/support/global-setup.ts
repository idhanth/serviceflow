import { chromium, request as playwrightRequest } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import {
  ADMIN,
  API_URL,
  BASE_URL,
  DEMO_CUSTOMER,
  EMPLOYEE,
  RUN_STATE,
  STORAGE,
} from "./config";

/**
 * Signs the three roles in once and parks their cookies, so the specs spend
 * their time on product behaviour rather than on the login form. The customer
 * is created fresh for every run through the real signup screen: a customer
 * with no history makes "your booking is pending" unambiguous, and it keeps a
 * run from depending on what an earlier run left behind.
 */
async function signIn(email: string, password: string, storagePath: string) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard", { timeout: 30_000 });

  mkdirSync(dirname(storagePath), { recursive: true });
  await context.storageState({ path: storagePath });
  await browser.close();
}

async function signUpCustomer(
  email: string,
  password: string,
  lastName: string,
  storagePath: string,
) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();

  // The signup page is scoped to one organization already (a real deployment
  // reaches it on the organization's own slug route), so there is no org field.
  await page.goto("/signup");
  await page.getByLabel("First name").fill("Robin");
  await page.getByLabel("Last name").fill(lastName);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/dashboard", { timeout: 30_000 });

  mkdirSync(dirname(storagePath), { recursive: true });
  await context.storageState({ path: storagePath });
  await browser.close();
}

export default async function globalSetup() {
  // Fail loudly and early if the stack is not up: a wall of selector timeouts
  // is a terrible way to learn the API is not running.
  const api = await playwrightRequest.newContext();
  const ready = await api.get(`${API_URL}/ready`).catch(() => null);
  if (!ready || !ready.ok()) {
    throw new Error(
      `The API is not ready at ${API_URL}. Start the stack with ./scripts/e2e.sh ` +
        `(services, API, worker, web) before running Playwright.`,
    );
  }
  const health = await ready.json();
  if (health.checks?.database !== "ok" || health.checks?.redis !== "ok") {
    throw new Error(`Dependencies are not healthy: ${JSON.stringify(health.checks)}`);
  }
  await api.dispose();

  const runId = Date.now().toString(36);
  // The surname carries the run id so it is unique in the UI: two runs against
  // the same development database would otherwise leave rows that look
  // identical, and a spec picking "the first row for Tester" could act on data
  // an earlier run left behind.
  const customer = {
    email: `e2e.customer.${runId}@example.com`,
    password: "e2e-password-2026",
    firstName: "Robin",
    lastName: `Tester${runId.toUpperCase()}`,
    runId,
  };

  // Three sign-ins and one sign-up for the whole run. Sign-in is rate limited
  // on purpose and the suite leaves that limiter on, so the specs reuse these
  // sessions instead of authenticating per test.
  await signIn(ADMIN.email, ADMIN.password, STORAGE.admin);
  await signIn(EMPLOYEE.email, EMPLOYEE.password, STORAGE.employee);
  await signIn(DEMO_CUSTOMER.email, DEMO_CUSTOMER.password, STORAGE.otherCustomer);
  await signUpCustomer(customer.email, customer.password, customer.lastName, STORAGE.customer);

  mkdirSync(dirname(RUN_STATE), { recursive: true });
  writeFileSync(RUN_STATE, JSON.stringify(customer, null, 2));
}
