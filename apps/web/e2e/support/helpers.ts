import { expect, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";

import { RUN_STATE } from "./config";

export type RunState = {
  runId: string;
  customerName?: string;
  customerId?: string;
  bookingId?: string;
  jobId?: string;
};

export function readRun(): RunState {
  return JSON.parse(readFileSync(RUN_STATE, "utf8")) as RunState;
}

export function writeRun(update: Partial<RunState>): RunState {
  const next = { ...readRun(), ...update };
  writeFileSync(RUN_STATE, JSON.stringify(next, null, 2));
  return next;
}

/** A JSON body from the API, loosely typed: specs read the fields they assert on. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- test fixtures read arbitrary API JSON
export type ApiJson = Record<string, any>;

export type ApiResult = { status: number; json: ApiJson; text: string };

/**
 * Calls the API from inside a signed-in page, through the same /api/proxy path the
 * application's own client code uses - so nothing here can reach data the UI
 * could not.
 */
export async function apiFromPage(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
): Promise<ApiResult> {
  const result = await page.evaluate(
    async ({ method, path, body }) => {
      const response = await fetch(`/api/proxy/${path.replace(/^\//, "")}`, {
        method,
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let json: unknown = null;
      try {
        json = JSON.parse(text);
      } catch {
        json = null;
      }
      return { status: response.status, json, text };
    },
    { method, path, body },
  );
  return result as ApiResult;
}

/** Collects browser console errors so a spec can assert the page stayed clean. */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("Failed to load resource")) {
      errors.push(message.text());
    }
  });
  return errors;
}

/** Nothing that should never reach a browser: stack traces, SQL, internal paths. */
export function expectNoInternals(text: string) {
  for (const needle of ["Traceback", "psycopg", "sqlalchemy", "SELECT ", "site-packages", "password_hash"]) {
    expect(text, `response leaked "${needle}"`).not.toContain(needle);
  }
}

/** The labels in the main sidebar, in order. */
export async function navLabels(page: Page): Promise<string[]> {
  const nav = page.getByRole("navigation", { name: "Main" }).first();
  await expect(nav).toBeVisible();
  return (await nav.getByRole("link").allTextContents()).map((label) => label.trim());
}

/** A date well past the seeded horizon, on a weekday the demo technician works. */
export function futureWeekday(daysAhead: number, weekday = 2): string {
  const date = new Date(Date.now() + daysAhead * 86_400_000);
  while (date.getUTCDay() !== weekday) date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}
