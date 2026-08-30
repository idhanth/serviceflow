import { expect, test } from "@playwright/test";

import { STORAGE } from "../support/config";
import { apiFor, collectConsoleErrors, jsonOf, runPlate, waitFor } from "../support/helpers";
import { confirmedJobForRunCustomer, DEMO_TECHNICIAN } from "../support/seedApi";
import type { Job, Photo } from "../support/types";

test.use({ storageState: STORAGE.employee });

/**
 * A genuine 1x1 PNG. The upload path is real - presigned POST straight to
 * MinIO, then the API verifies the stored object before writing metadata - so
 * the bytes have to be a real image, not a renamed text file.
 */
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test.describe("the employee's day", () => {
  const plate = runPlate("EMP");

  test("the job board shows only this employee's work", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await confirmedJobForRunCustomer({ plate, fromDaysAhead: 31 });

    await page.goto("/jobs");
    await expect(page.getByRole("heading", { name: /jobs|my work/i }).first()).toBeVisible();

    // Every row on an employee's board belongs to them, so no other technician
    // is named anywhere on it.
    const employeeApi = await apiFor("employee");
    const mine = await jsonOf<Job[]>(
      await employeeApi.get("/api/proxy/jobs?page_size=100"),
      "listing the employee's jobs",
    );
    const employees = new Set(mine.data.map((job) => job.employee.full_name));
    expect([...employees]).toEqual([DEMO_TECHNICIAN]);
    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("start, note, photograph and complete a job", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const { jobId } = await confirmedJobForRunCustomer({
      plate: `${plate}W`.slice(0, 12),
      fromDaysAhead: 32,
    });

    await page.goto(`/jobs/${jobId}`);
    await expect(page.getByRole("heading", { name: /express wash/i }).first()).toBeVisible();

    await page.getByRole("button", { name: "Start job" }).click();
    await expect(page.getByText("Job started")).toBeVisible();
    await expect(page.getByRole("button", { name: "Complete job" })).toBeVisible();

    // A note only the team sees.
    const noteBox = page.getByRole("textbox", { name: /new note/i });
    await noteBox.fill("E2E internal: clear coat is thin on the bonnet.");
    await page.getByRole("radio", { name: /team only/i }).check();
    await page.getByRole("button", { name: /add note/i }).click();
    await expect(page.getByText("Internal note added")).toBeVisible();

    // And one written for the customer.
    await noteBox.fill("E2E visible: all done, we also topped up the washer fluid.");
    await page.getByRole("radio", { name: /share with customer/i }).check();
    await page.getByRole("button", { name: /add note/i }).click();
    await expect(page.getByText("Note added for the customer")).toBeVisible();

    // A real upload: presigned POST to MinIO, then the API verifies the object.
    await page.getByLabel("Choose photos to upload").setInputFiles({
      name: "e2e-before.png",
      mimeType: "image/png",
      buffer: PNG_1X1,
    });

    const employeeApi = await apiFor("employee");
    const photos = await waitFor("the photo to be stored and recorded", async () => {
      const body = await jsonOf<Photo[]>(
        await employeeApi.get(`/api/proxy/jobs/${jobId}/photos`),
        "listing photos",
      );
      return body.data.length > 0 ? body.data : null;
    });
    expect(photos[0].file_size).toBeGreaterThan(0);
    expect(photos[0].mime_type).toBe("image/png");

    await page.getByRole("button", { name: "Complete job" }).click();
    await expect(page.getByText("Job completed")).toBeVisible();

    const job = await jsonOf<Job>(
      await employeeApi.get(`/api/proxy/jobs/${jobId}`),
      "reading the job",
    );
    expect(job.data.status).toBe("COMPLETED");
    expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
  });

  test("another technician's job is not reachable", async ({ page }) => {
    const admin = await apiFor("admin");
    const all = await jsonOf<Job[]>(await admin.get("/api/proxy/jobs?page_size=100"), "listing all jobs");
    const foreign = all.data.find((job) => job.employee.full_name !== DEMO_TECHNICIAN);
    expect(foreign, "no job belonging to another technician to test with").toBeTruthy();

    await page.goto(`/jobs/${foreign!.id}`);
    // Indistinguishable from a job that does not exist, and certainly not
    // workable: no start or complete control is offered.
    await expect(page.getByRole("button", { name: "Start job" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Complete job" })).toHaveCount(0);
    await expect(page.getByText(/not found|no longer available|couldn't find/i).first()).toBeVisible();
  });
});
