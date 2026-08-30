import { expect, test, type Browser, type Page } from "@playwright/test";

import { STORAGE } from "../support/config";
import { apiFor, jsonOf, looksSafe, runPlate } from "../support/helpers";
import { confirmedJobForRunCustomer } from "../support/seedApi";
import type { Booking, Job } from "../support/types";

async function pageFor(browser: Browser, storageState: string): Promise<Page> {
  const context = await browser.newContext({ storageState });
  return context.newPage();
}

/** A booking that belongs to the seeded demo customer, not to this run's. */
async function someoneElsesBooking() {
  const other = await apiFor("otherCustomer");
  const body = await jsonOf<Booking[]>(
    await other.get("/api/proxy/bookings?page_size=5"),
    "listing the other customer's bookings",
  );
  const booking = body.data[0];
  expect(booking, "the demo customer has no bookings to test isolation with").toBeTruthy();
  return booking as { id: string };
}

test.describe("what the browser will not let you do", () => {
  test("a customer cannot open another customer's booking", async ({ browser }) => {
    const foreign = await someoneElsesBooking();
    const page = await pageFor(browser, STORAGE.customer);

    // Compare what a person can actually perceive, not the HTML: script chunk
    // names and request ids differ between any two responses.
    await page.goto(`/bookings/${foreign.id}`);
    const foreignText = await page.getByRole("main").innerText();

    await page.goto("/bookings/2b1f6b0e-0000-4000-8000-000000000000");
    const madeUpText = await page.getByRole("main").innerText();

    expect(foreignText.trim()).toBe(madeUpText.trim());
    expect(looksSafe(foreignText)).toBeTruthy();
  });

  test("a customer has no job pages at all", async ({ browser }) => {
    const page = await pageFor(browser, STORAGE.customer);
    const admin = await apiFor("admin");
    const jobs = await jsonOf<Job[]>(await admin.get("/api/proxy/jobs?page_size=1"), "listing jobs");
    const job = jobs.data[0];

    await page.goto(`/jobs/${job.id}`);
    // Job pages are staff-only, so a customer is turned away before the page
    // renders anything about the job at all.
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("button", { name: "Start job" })).toHaveCount(0);
  });

  test("an employee cannot reach admin-only pages", async ({ browser }) => {
    const page = await pageFor(browser, STORAGE.employee);

    for (const route of ["/activity", "/customers", "/employees", "/services"]) {
      await page.goto(route);
      expect(page.url(), `${route} should not stay open for an employee`).not.toContain(route);
    }
  });

  test("the proxy refuses to carry a signed-out request", async ({ page }) => {
    // A browser with no session: the route handler must not attach a token.
    const response = await page.request.get("/api/proxy/customers", {
      headers: { cookie: "" },
    });
    expect(response.status()).toBe(401);
    const body = await response.text();
    expect(body).toContain("UNAUTHORIZED");
    expect(looksSafe(body)).toBeTruthy();
  });

  test("an internal note never reaches the customer's own payloads", async () => {
    // Write the note here rather than hoping the seed left one: a test that
    // skips itself when the data is inconvenient proves nothing.
    const employeeApi = await apiFor("employee");
    const customerApi = await apiFor("customer");
    const { jobId, bookingId } = await confirmedJobForRunCustomer({ plate: runPlate("SEC") });

    const secret = `E2E secret ${Date.now()}: do not show this to the customer.`;
    await jsonOf(
      await employeeApi.post(`/api/proxy/jobs/${jobId}/notes`, {
        data: { content: secret, visibility: "INTERNAL" },
      }),
      "adding an internal note",
    );

    // The staff see it.
    const staffView = await employeeApi.get(`/api/proxy/jobs/${jobId}/notes`);
    expect(await staffView.text()).toContain(secret);

    // The customer does not - not in the notes, not in the booking, not in
    // search, not in their notifications.
    for (const path of [
      `/api/proxy/jobs/${jobId}/notes`,
      `/api/proxy/bookings/${bookingId}`,
      "/api/proxy/bookings?page_size=100",
      "/api/proxy/notifications?page_size=50",
    ]) {
      const response = await customerApi.get(path);
      expect(await response.text(), `${path} leaked the internal note`).not.toContain(secret);
    }
  });
});
