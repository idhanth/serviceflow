import { expect, test } from "@playwright/test";

import { ADMIN, STORAGE } from "../support/config";
import { collectConsoleErrors, looksSafe, runCustomer } from "../support/helpers";

test.describe("authentication and route protection", () => {
  test("a signed-out visitor is sent to the login page", async ({ page }) => {
    const errors = collectConsoleErrors(page);

    for (const route of ["/dashboard", "/bookings", "/jobs", "/customers", "/activity"]) {
      await page.goto(route);
      await expect(page).toHaveURL(/\/login/);
      await expect(page.getByRole("heading", { name: /sign in to serviceflow/i })).toBeVisible();
    }

    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("a wrong password is refused with a message that gives nothing away", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: /sign in/i }).click();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    const message = (await alert.textContent()) ?? "";
    expect(looksSafe(message)).toBeTruthy();
    // It must not confirm whether the account exists.
    expect(message.toLowerCase()).not.toContain("no account");
    await expect(page).toHaveURL(/\/login/);
  });

  test("an unknown account fails exactly like a wrong password", async ({ page }) => {
    async function messageFor(email: string, password: string) {
      await page.goto("/login");
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: /sign in/i }).click();
      await expect(page.getByRole("alert")).toBeVisible();
      return (await page.getByRole("alert").textContent()) ?? "";
    }

    const unknown = await messageFor("nobody.here@example.com", "some-password");
    const wrong = await messageFor(ADMIN.email, "some-password");
    expect(unknown).toBe(wrong);
  });

  test("the signed-in customer from this run lands on their dashboard", async ({ browser }) => {
    const context = await browser.newContext({ storageState: STORAGE.customer });
    const page = await context.newPage();
    const errors = collectConsoleErrors(page);

    await page.goto("/dashboard");
    await expect(page.getByText(runCustomer().firstName, { exact: false }).first()).toBeVisible();

    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
    await context.close();
  });
});
