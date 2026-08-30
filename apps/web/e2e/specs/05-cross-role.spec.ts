import { expect, test, type Browser, type Page } from "@playwright/test";

import { STORAGE } from "../support/config";
import {
  apiFor,
  collectConsoleErrors,
  findRowAcrossPages,
  jsonOf,
  mailFor,
  runCustomer,
  runPlate,
  waitFor,
} from "../support/helpers";
import {
  DEMO_TECHNICIAN,
  ensureVehicleViaApi,
  freeSlotForTechnician,
  serviceNamed,
} from "../support/seedApi";
import type { ActivityEntry, Booking, Photo } from "../support/types";

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const INTERNAL_NOTE = "E2E internal: swirl marks on the roof, quote a correction next time.";
const VISIBLE_NOTE = "E2E visible: your car is finished and the interior has been vacuumed.";

async function pageFor(browser: Browser, storageState: string): Promise<Page> {
  const context = await browser.newContext({ storageState });
  return context.newPage();
}

test.describe("one job, three roles", () => {
  test("a booking travels from request to completion and the customer sees only their half", async ({
    browser,
    request,
  }) => {
    test.slow(); // Three browsers, a real upload and a real email round trip.

    const plate = runPlate("X");
    const customer = runCustomer();
    const customerPage = await pageFor(browser, STORAGE.customer);
    const adminPage = await pageFor(browser, STORAGE.admin);
    const employeePage = await pageFor(browser, STORAGE.employee);
    const customerErrors = collectConsoleErrors(customerPage);

    // ---------------------------------------------------------------- book
    const customerApi = await apiFor("customer");
    const vehicleId = await ensureVehicleViaApi(plate);
    const service = await serviceNamed("Express Wash");

    await customerPage.goto("/bookings/new");
    await customerPage.getByRole("button", { name: /Express Wash/ }).click();
    await customerPage.getByRole("button", { name: new RegExp(plate) }).first().click();

    // A slot the demo technician can actually take, found rather than assumed.
    const { iso: slotIso } = await freeSlotForTechnician({ fromDaysAhead: 33 });
    const local = new Date(new Date(slotIso).getTime() - new Date().getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
    await customerPage.getByLabel("Preferred date and time").fill(local);
    await customerPage.getByRole("button", { name: "Review", exact: true }).click();
    await customerPage.getByRole("button", { name: "Request booking" }).click();
    await customerPage.waitForURL("**/bookings");
    await expect(customerPage.getByText(/pending/i).first()).toBeVisible();

    const bookingId = await waitFor("the new booking to exist", async () => {
      const response = await jsonOf<Booking[]>(
        await customerApi.get("/api/proxy/bookings?page_size=100"),
        "listing bookings",
      );
      const match = response.data.find(
        (booking) => booking.vehicle.id === vehicleId && booking.status === "PENDING",
      );
      return match?.id ?? null;
    });
    expect(service.id).toBeTruthy();

    // ------------------------------------------------------------- confirm
    // The customer leaves their bookings page open: the confirmation should
    // reach it over the event stream, without anyone pressing reload.
    await customerPage.goto("/bookings");

    await adminPage.goto("/bookings");
    await adminPage.getByRole("button", { name: "Pending", exact: true }).click();
    const queueRow = await findRowAcrossPages(adminPage, [customer.lastName, "Express Wash"]);
    await expect(queueRow).toBeVisible();
    await queueRow.click();
    await expect(adminPage.getByText(/Ranked by who is free/)).toBeVisible();

    // Assign the demo employee specifically, so the employee browser can work it.
    const maria = adminPage.locator("label").filter({ hasText: DEMO_TECHNICIAN }).first();
    await expect(maria.getByRole("radio")).toBeEnabled();
    await maria.getByRole("radio").check();
    await adminPage.getByRole("button", { name: "Confirm booking" }).click();
    await expect(adminPage.getByText(/Confirmed —/)).toBeVisible();

    // Realtime: the customer's open page updates on its own.
    await expect(customerPage.getByText(/confirmed/i).first()).toBeVisible({ timeout: 30_000 });

    const jobId = await waitFor("the job for this booking", async () => {
      const response = await jsonOf<Booking>(
        await customerApi.get(`/api/proxy/bookings/${bookingId}`),
        "reading the booking",
      );
      return response.data.job?.id ?? null;
    });

    // ---------------------------------------------------------------- work
    await employeePage.goto(`/jobs/${jobId}`);
    await employeePage.getByRole("button", { name: "Start job" }).click();
    await expect(employeePage.getByText("Job started")).toBeVisible();

    const noteBox = employeePage.getByRole("textbox", { name: /new note/i });
    await noteBox.fill(INTERNAL_NOTE);
    await employeePage.getByRole("radio", { name: /team only/i }).check();
    await employeePage.getByRole("button", { name: /add note/i }).click();
    await expect(employeePage.getByText("Internal note added")).toBeVisible();

    await noteBox.fill(VISIBLE_NOTE);
    await employeePage.getByRole("radio", { name: /share with customer/i }).check();
    await employeePage.getByRole("button", { name: /add note/i }).click();
    await expect(employeePage.getByText("Note added for the customer")).toBeVisible();

    await employeePage.getByLabel("Choose photos to upload").setInputFiles({
      name: "e2e-after.png",
      mimeType: "image/png",
      buffer: PNG_1X1,
    });
    const employeeApi = await apiFor("employee");
    await waitFor("the photo to be stored", async () => {
      const body = await jsonOf<Photo[]>(
        await employeeApi.get(`/api/proxy/jobs/${jobId}/photos`),
        "listing photos",
      );
      return body.data.length > 0;
    });

    await employeePage.getByRole("button", { name: "Complete job" }).click();
    await expect(employeePage.getByText("Job completed")).toBeVisible();

    // ------------------------------------------------- what the customer sees
    await customerPage.goto(`/bookings/${bookingId}`);
    await expect(customerPage.getByText(VISIBLE_NOTE)).toBeVisible();
    await expect(customerPage.getByText("Photos from your visit")).toBeVisible();

    // The internal note is nowhere in the customer's page - not hidden by CSS,
    // not in a data payload, simply not there.
    const html = await customerPage.content();
    expect(html).not.toContain(INTERNAL_NOTE);
    expect(html).not.toContain("swirl marks");

    // Nor in what the API gives that customer, which is the boundary that matters.
    const customerJson = await customerApi.get(`/api/proxy/bookings/${bookingId}`);
    expect(await customerJson.text()).not.toContain("swirl marks");

    // Notifications reached them, in the app and by email.
    await expect(customerPage.getByRole("button", { name: /notifications/i })).toBeVisible();
    const mail = await waitFor("the completion email", async () => {
      const messages = await mailFor(request, customer.email);
      return messages.some((message) => /finished|complete/i.test(message.Subject))
        ? messages
        : null;
    });
    expect(mail.length).toBeGreaterThan(0);

    // ----------------------------------------------- the trail an admin reads
    const admin = await apiFor("admin");
    const feed = await jsonOf<ActivityEntry[]>(
      await admin.get(`/api/proxy/activity?resource_id=${jobId}&sort=created_at`),
      "reading the activity feed",
    );
    const actions = feed.data.map((entry) => entry.action);
    // The notes are audited against the job too, so assert the lifecycle in
    // order rather than demanding it be the only thing that happened.
    expect(actions.filter((action) => action.startsWith("JOB_"))).toEqual([
      "JOB_ASSIGNED",
      "JOB_STARTED",
      "JOB_COMPLETED",
    ]);
    expect(actions.filter((action) => action === "NOTE_ADDED")).toHaveLength(2);

    await adminPage.goto("/activity");
    await expect(
      adminPage.getByRole("row").filter({ hasText: "Job completed" }).first(),
    ).toBeVisible();

    expect(customerErrors, `console errors: ${customerErrors.join(" | ")}`).toHaveLength(0);
  });
});
