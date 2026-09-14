import { expect, test } from "@playwright/test";

import { storageFor } from "../support/config";
import { apiFromPage, collectConsoleErrors, futureWeekday, readRun, writeRun, type ApiJson } from "../support/helpers";

test.use({ storageState: storageFor("dispatcher") });
test.describe.configure({ mode: "serial" });

const TIMES = ["9:00 AM", "9:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "1:00 PM", "1:30 PM", "2:00 PM", "3:00 PM"];

test("a dispatcher adds a customer", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const { runId } = readRun();
  const last = `Carter${runId.toUpperCase()}`;

  await page.goto("/customers");
  await expect(page.getByRole("heading", { name: "Customers", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Add customer" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("First name").fill("Morgan");
  await dialog.getByLabel("Last name").fill(last);
  await dialog.getByLabel("Email").fill(`morgan.${runId}@example.com`);
  await dialog.getByLabel("Phone").fill("+1 (847) 555-0199");
  await dialog.getByLabel("Service address").fill("77 Elm Court, Evanston, IL 60201");

  // Validation runs before anything is sent.
  await dialog.getByLabel("Email").fill("not-an-email");
  await dialog.getByRole("button", { name: "Add customer" }).click();
  await expect(dialog.getByText("Enter a valid email address.")).toBeVisible();
  await dialog.getByLabel("Email").fill(`morgan.${runId}@example.com`);
  await dialog.getByRole("button", { name: "Add customer" }).click();

  await expect(page.getByText(`Morgan ${last} added`)).toBeVisible();
  await page.getByRole("searchbox", { name: "Search customers" }).fill(last);
  const row = page.getByRole("link", { name: `Morgan ${last}` }).first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByRole("heading", { name: `Morgan ${last}`, level: 1 })).toBeVisible();
  writeRun({ customerName: `Morgan ${last}`, customerId: page.url().split("/").pop() });
  expect(errors).toEqual([]);
});

test("a dispatcher books the customer with a technician through the wizard", async ({ page }) => {
  const { customerName, customerId } = readRun();
  await page.goto(`/bookings/new?customer_id=${customerId}`);
  await page.getByRole("button", { name: /HVAC Inspection/ }).click();

  await page.getByLabel("Date").fill(futureWeekday(70 + (Date.now() % 20)));
  const alex = page.getByRole("radio", { name: /Alex Morgan/ });
  let booked = false;
  for (const time of TIMES) {
    await page.getByLabel("Start time").selectOption({ label: time });
    await expect(alex).toBeVisible();
    if (await alex.isEnabled()) {
      await alex.check();
      booked = true;
      break;
    }
  }
  expect(booked, "Alex Morgan should be free at one of the offered times").toBeTruthy();

  await page.getByRole("button", { name: "Review" }).click();
  await expect(page.getByText(customerName!)).toBeVisible();
  await page.getByRole("button", { name: "Confirm booking" }).click();

  await page.waitForURL(/\/bookings\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Confirmed").first()).toBeVisible();
  await expect(page.getByText("Alex Morgan", { exact: true })).toBeVisible();
  const bookingId = page.url().split("/").pop()!;
  const booking = await apiFromPage(page, "GET", `bookings/${bookingId}`);
  expect(booking.status).toBe(200);
  writeRun({ bookingId, jobId: booking.json.data.job.id });
});

test("a technician who is already booked cannot be chosen, and a lost race is explained", async ({ page }) => {
  const { bookingId } = readRun();
  const original = (await (async () => {
    await page.goto(`/bookings/${bookingId}`);
    return apiFromPage(page, "GET", `bookings/${bookingId}`);
  })()).json.data;

  // 1. The wizard itself shows Alex as booked at the time just taken.
  const customers = await apiFromPage(page, "GET", "customers?q=Mitchell&page_size=5");
  const sarah = customers.json.data.find((row: ApiJson) => row.user.full_name === "Sarah Mitchell");
  await page.goto(`/bookings/new?customer_id=${sarah.id}`);
  await page.getByRole("button", { name: /HVAC Inspection/ }).click();
  const start = new Date(original.requested_start);
  const local = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago" }).format(start);
  const clock = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }).format(start);
  await page.getByLabel("Date").fill(local);
  await page.getByLabel("Start time").selectOption({ label: clock });
  const alex = page.getByRole("radio", { name: /Alex Morgan/ });
  await expect(alex).toBeDisabled();
  await expect(page.getByText(/Already booked/).first()).toBeVisible();

  // 2. Someone else takes a free slot while this form sits on the review step.
  const later = new Date(start.getTime() + 3 * 60 * 60 * 1000);
  const laterClock = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }).format(later);
  await page.getByLabel("Start time").selectOption({ label: laterClock });
  await expect(alex).toBeEnabled();
  await alex.check();
  await page.getByRole("button", { name: "Review" }).click();

  const james = (await apiFromPage(page, "GET", "customers?q=Carter&page_size=10")).json.data.find(
    (row: ApiJson) => row.user.full_name === "James Carter",
  );
  const rival = await apiFromPage(page, "POST", "bookings", {
    customer_id: james.id,
    service_id: original.service.id,
    employee_id: original.job.employee_id,
    requested_start: later.toISOString(),
  });
  expect(rival.status).toBe(201);

  await page.getByRole("button", { name: "Confirm booking" }).click();
  const alert = page.getByRole("alert").filter({ hasText: "is already booked from" });
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("Alex Morgan");
  await expect(alert).toContainText("Choose another employee or time");
  await expect(page.getByRole("button", { name: "Choose another technician or time" })).toBeVisible();

  // Clean up the booking created for the race, so reruns start from the same place.
  await apiFromPage(page, "POST", `bookings/${rival.json.data.id}/cancel`, {});
});
