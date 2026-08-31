import {
  chromium,
  expect,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { readFileSync } from "node:fs";

import { BASE_URL, MAILPIT_URL, RUN_STATE, STORAGE, type Role } from "./config";

export type RunCustomer = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
  runId: string;
};

/** The customer global setup created for this run. */
export function runCustomer(): RunCustomer {
  return JSON.parse(readFileSync(RUN_STATE, "utf8")) as RunCustomer;
}

/**
 * A plate that is unique per run but identical for every test in that run.
 *
 * Derived from the run id on disk rather than from the clock: Playwright can
 * reload a spec file (it restarts a worker after a failure), and a value that
 * changed on reload would make one test add a vehicle the next cannot find.
 */
export function runPlate(prefix = "E2E"): string {
  return `${prefix}${runCustomer().runId.toUpperCase()}`.slice(0, 12);
}

/**
 * An API client that runs inside a signed-in page.
 *
 * The session cookie is httpOnly and Secure. Over http a browser makes the
 * localhost exception and sends it; Playwright's request contexts do not, so
 * calls issued outside a page come back 401. Running fetch inside the page also
 * means these calls travel the exact path the application's own client code
 * takes - through /api/proxy, with the token attached server-side - so nothing
 * here can reach data the UI could not.
 */
/** The shape of the API's envelopes, as much of it as a test needs. */
export interface PageMeta {
  page: number;
  page_size: number;
  pages: number;
  total: number;
}

export interface ApiBody<T> {
  data: T;
  meta: PageMeta;
}

export interface ApiLikeResponse {
  status(): number;
  ok(): boolean;
  headers(): Record<string, string>;
  text(): Promise<string>;
  json<T = unknown>(): Promise<T>;
}

export interface RoleClient {
  get(path: string, init?: { headers?: Record<string, string> }): Promise<ApiLikeResponse>;
  post(
    path: string,
    init?: { data?: unknown; headers?: Record<string, string> },
  ): Promise<ApiLikeResponse>;
}

const rolePages = new Map<Role, Page>();
let browser: Browser | null = null;
const openContexts: BrowserContext[] = [];

async function pageForRole(role: Role): Promise<Page> {
  const existing = rolePages.get(role);
  if (existing) return existing;

  browser ??= await chromium.launch();
  const context = await browser.newContext({ baseURL: BASE_URL, storageState: STORAGE[role] });
  openContexts.push(context);
  const page = await context.newPage();
  // Any same-origin document will do; fetch is relative to it.
  await page.goto("/dashboard");
  rolePages.set(role, page);
  return page;
}

function wrap(raw: { status: number; headers: Record<string, string>; body: string }): ApiLikeResponse {
  return {
    status: () => raw.status,
    ok: () => raw.status >= 200 && raw.status < 300,
    headers: () => raw.headers,
    text: async () => raw.body,
    json: async <T,>() => JSON.parse(raw.body) as T,
  };
}

export async function apiFor(role: Role): Promise<RoleClient> {
  const page = await pageForRole(role);

  const call = async (
    method: string,
    path: string,
    data?: unknown,
    headers?: Record<string, string>,
  ): Promise<ApiLikeResponse> => {
    const raw = await page.evaluate(
      async ({ method, path, data, headers }) => {
        const response = await fetch(path, {
          method,
          headers: {
            ...(data === undefined ? {} : { "Content-Type": "application/json" }),
            ...(headers ?? {}),
          },
          body: data === undefined ? undefined : JSON.stringify(data),
        });
        const collected: Record<string, string> = {};
        response.headers.forEach((value, key) => {
          collected[key] = value;
        });
        return { status: response.status, headers: collected, body: await response.text() };
      },
      { method, path, data, headers },
    );
    return wrap(raw);
  };

  return {
    get: (path, init) => call("GET", path, undefined, init?.headers),
    post: (path, init) => call("POST", path, init?.data ?? {}, init?.headers),
  };
}

/** Releases the pages the role clients keep open; called from global teardown. */
export async function closeRoleContexts(): Promise<void> {
  rolePages.clear();
  for (const context of openContexts.splice(0)) await context.close();
  await browser?.close();
  browser = null;
}

/** Reads a JSON body, failing with the response text rather than on undefined. */
export async function jsonOf<T>(response: ApiLikeResponse, what: string): Promise<ApiBody<T>> {
  expect(
    response.ok(),
    `${what} failed (${response.status()}): ${await response.text()}`,
  ).toBeTruthy();
  return response.json<ApiBody<T>>();
}

/**
 * Waits for a condition instead of sleeping. Every wait in this suite goes
 * through here or through Playwright's own auto-waiting assertions, so a slow
 * machine makes the suite slower rather than flaky.
 */
export async function waitFor<T>(
  describe: string,
  probe: () => Promise<T | null | undefined | false>,
  { timeout = 20_000, interval = 400 }: { timeout?: number; interval?: number } = {},
): Promise<T> {
  const deadline = Date.now() + timeout;
  let last: unknown;
  while (Date.now() < deadline) {
    try {
      const value = await probe();
      if (value) return value as T;
      last = value;
    } catch (error) {
      last = error;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error(`Timed out waiting for ${describe} (last result: ${String(last)})`);
}

/** Messages MailPit has captured for one address, newest first. */
export async function mailFor(
  request: APIRequestContext,
  address: string,
): Promise<{ Subject: string; Created: string }[]> {
  const response = await request.get(
    `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:${address}`)}&limit=20`,
  );
  if (!response.ok()) return [];
  const body = await response.json();
  return (body.messages ?? []) as { Subject: string; Created: string }[];
}

/** Collects browser console errors so a spec can assert the page stayed clean. */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

/** True when the text contains nothing that should never reach a browser. */
export function looksSafe(text: string): boolean {
  const forbidden = [
    "Traceback",
    "psycopg",
    "sqlalchemy",
    "SELECT ",
    "/Users/",
    "site-packages",
    "password_hash",
    "X-Amz-Signature",
  ];
  return !forbidden.some((needle) => text.includes(needle));
}

/**
 * Whether a locator becomes visible within a short budget.
 *
 * For stepping through paged or navigated views: each step gets a real wait for
 * the next render rather than an instant count, which would race React and skip
 * straight past the page being looked for.
 */
export async function appearsWithin(
  locator: import("@playwright/test").Locator,
  timeout = 2_000,
): Promise<boolean> {
  try {
    await expect(locator).toBeVisible({ timeout });
    return true;
  } catch {
    return false;
  }
}

/**
 * Finds a row in a paginated table, stepping through pages the way a person
 * would.
 *
 * The suite adds rows to shared queues over time, so "it is on the first page"
 * stops being true after a few runs. Paging is bounded and each step waits for
 * the next page to render.
 */
export async function findRowAcrossPages(
  page: Page,
  matchers: string[],
  { maxPages = 8 }: { maxPages?: number } = {},
): Promise<import("@playwright/test").Locator> {
  const rowFor = () => {
    let rows = page.getByRole("row");
    for (const text of matchers) rows = rows.filter({ hasText: text });
    return rows.first();
  };

  for (let step = 0; step < maxPages; step += 1) {
    if (await appearsWithin(rowFor(), 2_000)) return rowFor();

    const next = page.getByRole("button", { name: "Next" });
    if ((await next.count()) === 0 || (await next.isDisabled())) break;

    // Wait for the rows themselves to change rather than for any particular
    // wording in the pager, so this keeps working when that copy is redesigned.
    const firstRow = page.locator("tbody tr").first();
    const before = await firstRow.innerText().catch(() => "");
    await next.click();
    await expect
      .poll(async () => firstRow.innerText().catch(() => ""), { timeout: 10_000 })
      .not.toBe(before);
  }

  throw new Error(`no row matching ${matchers.join(" + ")} in the first ${maxPages} pages`);
}
