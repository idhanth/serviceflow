import { expect, test } from "@playwright/test";

import { ACCOUNTS, DEMO_PASSWORD, storageFor, type Role } from "../support/config";
import { collectConsoleErrors, navLabels } from "../support/helpers";

test("signs in through the form, lands on the dashboard and signs out", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in to ServiceFlow" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Explore as" })).toBeVisible();

  await page.getByLabel("Email").fill(ACCOUNTS.owner);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL("**/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(page.getByText("Northside Home Services").first()).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).first().click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await page.waitForURL("**/login");

  // A protected page now sends the visitor back to sign in.
  await page.goto("/jobs");
  await page.waitForURL(/\/login/);
  expect(errors).toEqual([]);
});

test("a wrong password is refused with a clear message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ACCOUNTS.dispatcher);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText(/didn.t match/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

const EXPECTED_NAV: Record<Role, { home: RegExp; labels: string[] }> = {
  owner: {
    home: /\/dashboard$/,
    labels: ["Dashboard", "Schedule", "Bookings", "Jobs", "Customers", "Employees", "Services", "Activity", "Settings"],
  },
  dispatcher: { home: /\/dashboard$/, labels: ["Dashboard", "Schedule", "Bookings", "Jobs", "Customers"] },
  technician: { home: /\/schedule$/, labels: ["My Schedule", "My Jobs", "My Availability"] },
  customer: { home: /\/bookings$/, labels: ["My Bookings", "Book Service", "Profile"] },
  analyst: {
    home: /\/dashboard$/,
    labels: ["Dashboard", "Schedule", "Bookings", "Jobs", "Customers", "Employees", "Services", "Activity", "Settings"],
  },
  platform: { home: /\/platform$/, labels: ["Businesses"] },
  rival: {
    home: /\/dashboard$/,
    labels: ["Dashboard", "Schedule", "Bookings", "Jobs", "Customers", "Employees", "Services", "Activity", "Settings"],
  },
};

for (const [role, expected] of Object.entries(EXPECTED_NAV) as [Role, (typeof EXPECTED_NAV)[Role]][]) {
  test.describe(`navigation for ${role}`, () => {
    test.use({ storageState: storageFor(role) });

    test(`shows exactly what a ${role} can use`, async ({ page }) => {
      await page.goto("/dashboard");
      await expect(page).toHaveURL(expected.home);
      expect(await navLabels(page)).toEqual(expected.labels);
    });
  });
}
