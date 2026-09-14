import { expect, test } from "@playwright/test";

import { storageFor } from "../support/config";
import { apiFromPage, expectNoInternals, readRun } from "../support/helpers";

test.describe("another business", () => {
  test.use({ storageState: storageFor("rival") });

  test("cannot open Northside's job or booking, in the UI or through the API", async ({ page }) => {
    const { jobId, bookingId } = readRun();
    await page.goto(`/jobs/${jobId}`);
    await expect(page.getByText("We couldn't find that job.")).toBeVisible();

    for (const path of [`bookings/${bookingId}`, `jobs/${jobId}`]) {
      const response = await apiFromPage(page, "GET", path);
      expect(response.status).toBe(404);
      expect(response.json.error.code).toBe("NOT_FOUND");
      expectNoInternals(response.text);
    }
    const write = await apiFromPage(page, "PATCH", `jobs/${jobId}`, { status: "CANCELLED" });
    expect(write.status).toBe(404);
  });
});

test.describe("a read-only analyst", () => {
  test.use({ storageState: storageFor("analyst") });

  test("sees operations but no way to change them, and the API refuses changes", async ({ page }) => {
    const { jobId } = readRun();
    await page.goto("/bookings");
    await expect(page.getByRole("heading", { name: "Bookings", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "New booking" })).toHaveCount(0);
    await expect(page.getByText("Read-only access").first()).toBeVisible();

    await page.goto(`/jobs/${jobId}`);
    await expect(page.getByText("You have read-only access to this job.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel job" })).toHaveCount(0);

    const refused = await apiFromPage(page, "POST", `jobs/${jobId}/cancel`);
    expect(refused.status).toBe(403);
    expect(refused.json.error.code).toBe("INVALID_ROLE");
  });
});

test.describe("a customer", () => {
  test.use({ storageState: storageFor("customer") });

  test("is kept out of staff screens and staff APIs", async ({ page }) => {
    await page.goto("/customers");
    await expect(page).toHaveURL(/\/bookings$/);
    await expect(page.getByRole("heading", { name: "My Bookings", level: 1 })).toBeVisible();
    const listing = await apiFromPage(page, "GET", "customers");
    expect(listing.status).toBe(403);
  });
});

test.describe("a technician", () => {
  test.use({ storageState: storageFor("technician") });

  test("cannot reach business settings", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/schedule$/);
    const response = await apiFromPage(page, "PATCH", "organizations/current", { name: "Renamed" });
    expect(response.status).toBe(403);
  });
});

test.describe("the platform administrator", () => {
  test.use({ storageState: storageFor("platform") });

  test("sees businesses but not what is inside them", async ({ page }) => {
    await page.goto("/platform");
    await expect(page.getByRole("cell", { name: /Northside Home Services/ })).toBeVisible();
    await page.goto("/customers");
    await expect(page).toHaveURL(/\/platform$/);
    const response = await apiFromPage(page, "GET", "bookings");
    expect(response.status).toBe(403);
    expect(response.json.error.code).toBe("TENANT_ACCESS_DENIED");
  });
});
