import { expect, test, type Page } from "@playwright/test";

import { STORAGE } from "../support/config";
import { apiFor, collectConsoleErrors, jsonOf, runPlate } from "../support/helpers";
import type { Booking } from "../support/types";

test.use({ storageState: STORAGE.customer });

/** Walks the four wizard steps and submits. Returns the plate it booked for. */
async function bookThroughTheWizard(
  page: Page,
  { plate, daysAhead, notes }: { plate: string; daysAhead: number; notes?: string },
) {
  await page.goto("/bookings/new");

  await expect(page.getByRole("region", { name: "Choose a service" })).toBeVisible();
  await page.getByRole("button", { name: /Express Wash/ }).click();

  await expect(page.getByRole("region", { name: "Choose a vehicle" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(plate) }).first().click();

  const slot = new Date(Date.now() + daysAhead * 86_400_000);
  slot.setHours(11, 0, 0, 0);
  const local = new Date(slot.getTime() - slot.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
  await page.getByLabel("Preferred date and time").fill(local);
  if (notes) await page.getByLabel(/Anything we should know/).fill(notes);
  await page.getByRole("button", { name: "Review", exact: true }).click();

  await expect(page.getByRole("region", { name: "Review and submit" })).toBeVisible();
  await page.getByRole("button", { name: "Request booking" }).click();
}

/**
 * Adds the run's vehicle if this customer does not have it yet.
 *
 * The garage of a run's freshly signed-up customer holds either nothing or this
 * one vehicle, so waiting for "the plate or the empty state" is a real settled
 * signal. Checking visibility without that wait races the page load and would
 * add the vehicle again on every call.
 */
async function ensureVehicle(page: Page, plate: string) {
  await page.goto("/vehicles");
  // Settle on either the empty state or a rendered vehicle card before
  // deciding: an immediate visibility check races the fetch and would add the
  // vehicle a second time.
  const card = page.getByText(plate).first();
  const anyVehicle = page.getByRole("heading", { name: /^\d{4} / }).first();
  await expect(card.or(page.getByText("No vehicles yet")).or(anyVehicle).first()).toBeVisible();
  if ((await card.count()) > 0) return;

  await page.getByRole("button", { name: /add a vehicle|add vehicle/i }).first().click();
  await page.getByLabel("Year").fill("2021");
  await page.getByLabel("Make").fill("Subaru");
  await page.getByLabel("Model").fill("Outback");
  await page.getByLabel("Colour").fill("Slate");
  await page.getByLabel("License plate").fill(plate);
  await page.getByRole("button", { name: "Add vehicle" }).click();
  await expect(page.getByText(plate).first()).toBeVisible();
}

test.describe("the customer's own journey", () => {
  const plate = runPlate("CUS");

  test("a new customer starts with an empty garage and adds a vehicle", async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await page.goto("/vehicles");
    await expect(page.getByRole("heading", { name: /my vehicles/i })).toBeVisible();
    await expect(page.getByText("No vehicles yet")).toBeVisible();

    await page.getByRole("button", { name: /add a vehicle|add vehicle/i }).first().click();
    await page.getByLabel("Year").fill("2021");
    await page.getByLabel("Make").fill("Subaru");
    await page.getByLabel("Model").fill("Outback");
    await page.getByLabel("Colour").fill("Slate");
    await page.getByLabel("License plate").fill(plate);
    await page.getByRole("button", { name: "Add vehicle" }).click();

    // The garage shows it without a reload.
    await expect(page.getByText(plate)).toBeVisible();
    await expect(page.getByRole("heading", { name: "2021 Subaru Outback" }).first()).toBeVisible();
    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("booking a service leaves a pending request the customer can see", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await ensureVehicle(page, plate);

    await bookThroughTheWizard(page, { plate, daysAhead: 12, notes: "E2E: please be gentle." });

    await page.waitForURL("**/bookings");
    const upcoming = page.getByRole("main");
    await expect(upcoming.getByText("Express Wash").first()).toBeVisible();
    await expect(upcoming.getByText(/pending/i).first()).toBeVisible();
    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("submitting the same booking twice creates one booking, not two", async ({ page }) => {
    const api = await apiFor("customer");
    const before = await jsonOf<Booking[]>(
      await api.get("/api/proxy/bookings?page_size=100"),
      "listing bookings",
    );
    const countBefore = before.meta.total as number;
    await ensureVehicle(page, plate);

    await page.goto("/bookings/new");
    await page.getByRole("button", { name: /Interior Detail/ }).click();
    await page.getByRole("button", { name: new RegExp(plate) }).first().click();

    const slot = new Date(Date.now() + 15 * 86_400_000);
    slot.setHours(9, 0, 0, 0);
    await page
      .getByLabel("Preferred date and time")
      .fill(new Date(slot.getTime() - slot.getTimezoneOffset() * 60_000).toISOString().slice(0, 16));
    await page.getByRole("button", { name: "Review", exact: true }).click();

    // Two clicks as fast as the browser allows, on the same unchanged payload:
    // the second must replay the first rather than book a second appointment.
    const submit = page.getByRole("button", { name: "Request booking" });
    await Promise.all([
      submit.click(),
      submit.click({ force: true, noWaitAfter: true }).catch(() => undefined),
    ]);
    await page.waitForURL("**/bookings");

    const body = await jsonOf<Booking[]>(
      await api.get("/api/proxy/bookings?page_size=100"),
      "listing bookings",
    );
    expect(body.meta.total).toBe(countBefore + 1);

    const interior = body.data.filter((booking) => booking.service.name === "Interior Detail");
    expect(interior).toHaveLength(1);
  });

  test("a customer cannot reach staff areas from the browser", async ({ page }) => {
    for (const route of ["/customers", "/employees", "/activity", "/calendar"]) {
      await page.goto(route);
      await expect(page).not.toHaveURL(new RegExp(route.replace("/", "\\/")));
    }
  });
});
