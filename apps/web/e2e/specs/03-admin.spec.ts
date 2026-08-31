import { expect, test } from "@playwright/test";

import { STORAGE } from "../support/config";
import {
  apiFor,
  appearsWithin,
  collectConsoleErrors,
  findRowAcrossPages,
  jsonOf,
  runCustomer,
  runPlate,
} from "../support/helpers";
import { anExistingFutureJob, freeSlotForTechnician, pendingBookingAt } from "../support/seedApi";
import type { Booking, Job } from "../support/types";

test.use({ storageState: STORAGE.admin });

/**
 * How far out this spec books. Beyond the seed's 21-day horizon on purpose: the
 * pending queue is paginated latest-first, so a booking further out than any
 * seeded one is deterministically on the first page instead of buried. The
 * exact slot is then chosen from what is actually free.
 */
const DAYS_AHEAD = 30;

test.describe("the admin's review and assignment work", () => {
  const plate = runPlate("ADM");

  test("a pending request reaches the queue and can be confirmed with a ranked pick", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const { iso } = await freeSlotForTechnician({ fromDaysAhead: DAYS_AHEAD });
    const booking = await pendingBookingAt({ plate, iso });

    await page.goto("/bookings");
    await page.getByRole("button", { name: "Pending", exact: true }).click();

    const row = await findRowAcrossPages(page, [runCustomer().lastName, "Express Wash"]);
    await expect(row).toBeVisible();
    await row.click();

    // The sheet explains its ranking rather than just listing people.
    await expect(page.getByText(/Ranked by who is free/)).toBeVisible();
    await expect(page.getByText("Best fit")).toBeVisible();

    const recommended = page.getByRole("radio").first();
    await expect(recommended).toBeEnabled();
    await recommended.check();
    await page.getByRole("button", { name: "Confirm booking" }).click();

    // The toast names the technician who took it.
    await expect(page.getByText(/Confirmed —/)).toBeVisible();
    // This booking specifically has left the pending queue. Counting rows for
    // the customer would be wrong: the run has other pending requests of the
    // same service, and they are supposed to still be there.
    await page.getByRole("button", { name: "Pending", exact: true }).click();
    const admin = await apiFor("admin");
    const stillPending = await jsonOf<Booking[]>(
      await admin.get("/api/proxy/bookings?status=PENDING&page_size=100"),
      "listing the pending queue",
    );
    expect(stillPending.data.map((row) => row.id)).not.toContain(booking.id);

    // And a job now exists for it, which is the invariant behind the badge.
    const customerApi = await apiFor("customer");
    const detail = await jsonOf<Booking>(
      await customerApi.get(`/api/proxy/bookings/${booking.id}`),
      "reading the booking",
    );
    const body = detail.data;
    expect(body.status).toBe("CONFIRMED");
    expect(body.job).toBeTruthy();
    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("the assignment appears on the calendar", async ({ page }) => {
    const calendarLoaded = (action: Promise<unknown>) =>
      Promise.all([
        page.waitForResponse(
          (response) => response.url().includes("calendar") && response.status() === 200,
        ),
        action,
      ]);

    await calendarLoaded(page.goto("/calendar"));
    await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();

    // Look for this run's own job, not just any booking that happens to share a
    // service name. Only visible matches count: the page renders a desktop grid
    // and a mobile list, and the hidden one would satisfy a naive count.
    const admin = await apiFor("admin");
    const jobs = await jsonOf<Job[]>(
      await admin.get(`/api/proxy/jobs?q=${encodeURIComponent(runCustomer().lastName)}&page_size=10`),
      "finding this run's job",
    );
    const job = jobs.data[0];
    expect(job, "this run has no job to find on the calendar").toBeTruthy();

    const entry = page.locator(`a[href="/jobs/${job.id}"]`).filter({ visible: true }).first();
    let found = await appearsWithin(entry);
    for (let week = 0; week < 8 && !found; week += 1) {
      await calendarLoaded(page.getByRole("button", { name: "Next week" }).click());
      found = await appearsWithin(entry);
    }

    expect(found, "this run's job never appeared on the calendar").toBeTruthy();
    await expect(entry).toContainText("Express Wash");
  });

  test("the Activity feed records who confirmed the booking", async ({ page }) => {
    await page.goto("/activity");
    await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();

    const confirmed = page.getByRole("row").filter({ hasText: "Confirmed a booking" }).first();
    await expect(confirmed).toBeVisible();
    await expect(confirmed).toContainText("Alex Rivera");

    await page.getByRole("button", { name: "Bookings", exact: true }).click();
    await expect(page.getByRole("row").filter({ hasText: "Booking" }).first()).toBeVisible();
  });

  test("search finds the customer created by this run", async ({ page }) => {
    await page.goto("/customers");
    const search = page.getByLabel(/search customers/i);
    await search.fill(runCustomer().lastName);
    await expect(
      page.getByRole("row").filter({ hasText: runCustomer().email }).first(),
    ).toBeVisible();

    await search.fill("zzz-nobody-matches-this");
    await expect(page.getByText(/no customers|nobody matches/i).first()).toBeVisible();
  });

  test("an employee already booked at that hour cannot be assigned again", async ({ page }) => {
    // Book straight on top of an assignment that already exists, so the person
    // holding it is provably busy at that hour.
    const { start, employeeName } = await anExistingFutureJob();
    await pendingBookingAt({
      plate: `${plate}B`.slice(0, 12),
      serviceName: "Interior Detail",
      iso: start,
    });

    await page.goto("/bookings");
    await page.getByRole("button", { name: "Pending", exact: true }).click();
    const colliding = await findRowAcrossPages(page, [runCustomer().lastName, "Interior Detail"]);
    await colliding.click();
    await expect(page.getByText(/Ranked by who is free/)).toBeVisible();

    // The conflict is refused before an admin can create it: the busy person is
    // labelled and cannot be selected at all.
    const busyLabel = page.locator("label").filter({ hasText: employeeName }).first();
    await expect(busyLabel).toContainText("Busy");
    await expect(busyLabel.getByRole("radio")).toBeDisabled();
  });
});
