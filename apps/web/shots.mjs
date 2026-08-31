import { chromium, request } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const OUT = process.env.SHOT_DIR || "/tmp/shots";
const WIDTH = Number(process.env.WIDTH || 1440);
const HEIGHT = Number(process.env.HEIGHT || 900);
const THEME = process.env.THEME || "light";
const TAG = process.env.TAG || "base";
const ROLE = process.env.ROLE || "admin";
const PAGES = (process.env.PAGES || "/dashboard,/bookings,/jobs,/calendar,/customers,/employees,/services,/activity").split(",");

const ACCOUNTS = {
  admin: ["admin@serviceflow.demo", "demo1234"],
  employee: ["employee@serviceflow.demo", "demo1234"],
  customer: ["customer@serviceflow.demo", "demo1234"],
};

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({
  baseURL: "http://localhost:3000",
  viewport: { width: WIDTH, height: HEIGHT },
  colorScheme: THEME === "dark" ? "dark" : "light",
  deviceScaleFactor: 2,
});
// Authenticate through the app's own login route and hand the cookies to the
// browser. Driving the login form works, but the dev server hydrates slowly
// enough that a scripted click can beat React to it - and this script is here
// to look at pages, not to test sign-in.
// Sessions are cached on disk between runs. Sign-in is rate limited by design,
// and a screenshot pass that logs in every time trips a real protection.
const [email, password] = ACCOUNTS[ROLE];
const cacheFile = `/tmp/shots/.session-${ROLE}.json`;
let cookies;

if (existsSync(cacheFile)) {
  cookies = JSON.parse(readFileSync(cacheFile, "utf8"));
}

async function signIn() {
  const api = await request.newContext({ baseURL: "http://localhost:3000" });
  const response = await api.post("/api/auth/login", { data: { email, password } });
  if (!response.ok()) throw new Error(`login failed: ${response.status()} ${await response.text()}`);
  const state = await api.storageState();
  await api.dispose();
  writeFileSync(cacheFile, JSON.stringify(state.cookies));
  return state.cookies;
}

if (!cookies) cookies = await signIn();
await ctx.addCookies(cookies);

const probe = await ctx.newPage();
await probe.goto("/dashboard");
if (probe.url().includes("/login")) {
  await ctx.clearCookies();
  await ctx.addCookies(await signIn());
}
await probe.close();

const page = await ctx.newPage();

for (const path of PAGES) {
  await page.goto(path);
  await page.waitForLoadState("networkidle").catch(() => {});
  // Wait for real content: skeletons are not what we are here to look at.
  await page
    .waitForFunction(() => document.querySelectorAll("[data-slot='skeleton']").length === 0, {
      timeout: 20000,
    })
    .catch(() => {});
  await page.waitForTimeout(900);
  const name = path.replace(/\//g, "") || "root";
  const file = `${OUT}/${TAG}-${ROLE}-${name}-${WIDTH}-${THEME}.png`;
  await page.screenshot({ path: file });
  console.log(file);
}
await browser.close();
