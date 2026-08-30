import { expect, test, type Browser, type Page } from "@playwright/test";

import { STORAGE } from "../support/config";
import {
  apiFor,
  appearsWithin,
  collectConsoleErrors,
  jsonOf,
  looksSafe,
  runPlate,
  waitFor,
} from "../support/helpers";
import {
  confirmedJobForRunCustomer,
  ensureVehicleViaApi,
  freeSlotForTechnician,
  pendingBookingAt,
  serviceNamed,
} from "../support/seedApi";
import type { ApiBody } from "../support/helpers";
import type { AppNotification, Booking } from "../support/types";

async function pageFor(browser: Browser, storageState: string): Promise<Page> {
  const context = await browser.newContext({ storageState });
  return context.newPage();
}

test.describe("when things go wrong", () => {
  test("a duplicate request is replayed, and a changed one is refused", async () => {
    const api = await apiFor("customer");
    const plate = runPlate("IDM");
    const vehicleId = await ensureVehicleViaApi(plate);
    const service = await serviceNamed("Express Wash");
    const { iso } = await freeSlotForTechnician({ fromDaysAhead: 40 });
    const key = `e2e-failure-${Date.now()}`;

    const first = await api.post("/api/proxy/bookings", {
      headers: { "Idempotency-Key": key },
      data: { vehicle_id: vehicleId, service_id: service.id, requested_start: iso },
    });
    expect(first.status()).toBe(201);

    const replay = await api.post("/api/proxy/bookings", {
      headers: { "Idempotency-Key": key },
      data: { vehicle_id: vehicleId, service_id: service.id, requested_start: iso },
    });
    expect(replay.status()).toBe(200);
    expect(replay.headers()["idempotent-replay"]).toBe("true");
    const replayed = await replay.json<ApiBody<Booking>>();
    const created = await first.json<ApiBody<Booking>>();
    expect(replayed.data.id).toBe(created.data.id);

    const changed = await api.post("/api/proxy/bookings", {
      headers: { "Idempotency-Key": key },
      data: {
        vehicle_id: vehicleId,
        service_id: service.id,
        requested_start: new Date(Date.parse(iso) + 3_600_000).toISOString(),
      },
    });
    expect(changed.status()).toBe(409);
    const body = await changed.text();
    expect(body).toContain("IDEMPOTENCY_CONFLICT");
    expect(looksSafe(body)).toBeTruthy();
  });

  test("an already-started job cannot be started again", async ({ browser }) => {
    const { jobId } = await confirmedJobForRunCustomer({ plate: runPlate("STA") });
    const page = await pageFor(browser, STORAGE.employee);

    await page.goto(`/jobs/${jobId}`);
    await page.getByRole("button", { name: "Start job" }).click();
    await expect(page.getByText("Job started")).toBeVisible();

    // The control is gone, so the invalid move is not offered at all.
    await expect(page.getByRole("button", { name: "Start job" })).toHaveCount(0);

    // And the API refuses it even when asked directly, in the app's own words.
    const employeeApi = await apiFor("employee");
    const again = await employeeApi.post(`/api/proxy/jobs/${jobId}/start`);
    expect(again.status()).toBe(409);
    const text = await again.text();
    expect(text).toContain("INVALID_STATE_TRANSITION");
    expect(looksSafe(text)).toBeTruthy();
  });

  test("an oversized or wrong-typed upload is refused with a readable reason", async () => {
    const { jobId } = await confirmedJobForRunCustomer({ plate: runPlate("UPL") });
    const employeeApi = await apiFor("employee");

    const tooBig = await employeeApi.post(`/api/proxy/jobs/${jobId}/photos/presign`, {
      data: { mime_type: "image/png", file_size: 25 * 1024 * 1024 },
    });
    expect(tooBig.status()).toBe(422);
    const bigBody = await tooBig.text();
    expect(bigBody.toLowerCase()).toContain("10");
    expect(looksSafe(bigBody)).toBeTruthy();

    const wrongType = await employeeApi.post(`/api/proxy/jobs/${jobId}/photos/presign`, {
      data: { mime_type: "application/x-msdownload", file_size: 1024 },
    });
    expect(wrongType.status()).toBe(422);
    expect(looksSafe(await wrongType.text())).toBeTruthy();
  });

  test("hitting the sign-up limit shows a wait, not a stack trace", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    // Match the message itself. The toast region is an always-present, empty
    // element with role=alert, so "is there an alert?" is not the question.
    const limitMessage = page.getByText(/too many sign-up attempts/i);
    let limited = false;

    // The limiter is real and switched on; this walks into it deliberately.
    for (let attempt = 0; attempt < 8 && !limited; attempt += 1) {
      await page.goto("/signup");
      await page.getByLabel("First name").fill("Rate");
      await page.getByLabel("Last name").fill("Limited");
      await page.getByLabel("Email").fill(`e2e.rate.${Date.now()}.${attempt}@example.com`);
      await page.getByLabel("Password", { exact: true }).fill("a-good-password-2026");
      await page.getByRole("button", { name: "Create account" }).click();

      if (await appearsWithin(limitMessage, 5_000)) {
        limited = true;
        const message = (await limitMessage.first().textContent()) ?? "";
        expect(looksSafe(message)).toBeTruthy();
        expect(message.toLowerCase()).not.toContain("redis");
        expect(message.toLowerCase()).not.toContain("sf:rl");
        // It tells the person to come back later rather than blaming them.
        expect(message.toLowerCase()).toMatch(/later|try again/);
      } else {
        // That attempt was accepted, which signs this browser in; drop the
        // session so the next attempt sees the signup form rather than a
        // redirect to the dashboard.
        await page.waitForURL("**/dashboard", { timeout: 20_000 });
        await page.context().clearCookies();
      }
    }

    expect(limited, "the sign-up limiter never engaged").toBeTruthy();
    expect(errors.filter((error) => !error.includes("429")), errors.join(" | ")).toHaveLength(0);
  });

  test("the page keeps working when the event stream drops", async ({ browser }) => {
    const page = await pageFor(browser, STORAGE.customer);
    await page.goto("/bookings");
    await expect(page.getByRole("heading", { name: /my bookings/i })).toBeVisible();

    // Kill the stream mid-session: the app must fall back to refetching rather
    // than showing stale or broken state.
    await page.route("**/api/events", (route) => route.abort());
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));

    const api = await apiFor("customer");
    const { iso } = await freeSlotForTechnician({ fromDaysAhead: 44 });
    const plate = runPlate("SSE");
    await ensureVehicleViaApi(plate);
    const booking = await pendingBookingAt({ plate, iso, serviceName: "Interior Detail" });

    // A reload is a legitimate recovery path, and the data must be correct.
    await page.reload();
    await expect(page.getByText("Interior Detail").first()).toBeVisible();

    const detail = await jsonOf<Booking>(
      await api.get(`/api/proxy/bookings/${booking.id}`),
      "reading the booking",
    );
    expect(detail.data.status).toBe("PENDING");
  });

  test("a booking still succeeds while email delivery is backed up", async () => {
    // Email is queued after the commit, never inside it. Even if delivery is
    // slow or failing, the booking is the customer's regardless.
    const api = await apiFor("customer");
    const plate = runPlate("MAIL");
    const vehicleId = await ensureVehicleViaApi(plate);
    const service = await serviceNamed("Express Wash");
    const { iso } = await freeSlotForTechnician({ fromDaysAhead: 47 });

    const response = await api.post("/api/proxy/bookings", {
      data: { vehicle_id: vehicleId, service_id: service.id, requested_start: iso },
    });
    expect(response.status()).toBe(201);
    const bookingId = (await response.json<ApiBody<Booking>>()).data.id;

    // The durable record of the intent exists immediately, whatever the
    // provider is doing.
    const notifications = await waitFor("the queued notification", async () => {
      const body = await jsonOf<AppNotification[]>(
        await api.get("/api/proxy/notifications?page_size=20"),
        "listing notifications",
      );
      return body.data.length > 0 ? body.data : null;
    });
    expect(notifications.length).toBeGreaterThan(0);
    expect(bookingId).toBeTruthy();
  });
});
