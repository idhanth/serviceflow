import { expect, test } from "@playwright/test";

import { storageFor } from "../support/config";
import { collectConsoleErrors, readRun } from "../support/helpers";

test.use({ storageState: storageFor("technician") });

test("the assigned technician starts and completes the job", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const { jobId } = readRun();

  await page.goto("/jobs");
  await expect(page.getByRole("heading", { name: "My Jobs", level: 1 })).toBeVisible();

  await page.goto(`/jobs/${jobId}`);
  await expect(page.getByRole("heading", { name: "HVAC Inspection", level: 1 })).toBeVisible();
  await expect(page.getByText("Scheduled").first()).toBeVisible();

  await page.getByRole("button", { name: "Start job" }).click();
  await expect(page.getByText("Job started")).toBeVisible();
  await expect(page.getByText("In progress").first()).toBeVisible();

  await page.getByLabel("Completion summary").fill("Replaced the filter and cleaned the coils.");
  await page.getByRole("button", { name: "Complete job" }).click();
  await expect(page.getByText("Job completed")).toBeVisible();
  await expect(page.getByText("Completed").first()).toBeVisible();
  await expect(page.getByText("Replaced the filter and cleaned the coils.")).toBeVisible();
  expect(errors).toEqual([]);
});
