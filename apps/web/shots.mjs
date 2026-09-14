// Capture the README screenshots from a running stack (docker compose up).
//
//   node shots.mjs                      # writes docs/screenshots/*.png
//   SHOT_DIR=/tmp/shots WIDTH=390 node shots.mjs
//
// Each shot signs in as the role that would actually use the screen, through
// the app's own login route, so what is captured is what that role sees.
import { chromium, request } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:3000";
const OUT = process.env.SHOT_DIR || fileURLToPath(new URL("../../docs/screenshots/", import.meta.url));
const WIDTH = Number(process.env.WIDTH || 1440);
const HEIGHT = Number(process.env.HEIGHT || 900);
const PASSWORD = "demo1234";

const SHOTS = [
  { name: "login", role: null, path: "/login", ready: { role: "heading", name: "Sign in to ServiceFlow" } },
  { name: "dashboard", role: "owner", path: "/dashboard", ready: { role: "heading", name: "Dashboard" } },
  { name: "schedule", role: "dispatcher", path: "/schedule", ready: { role: "heading", name: "Schedule" } },
  { name: "booking-wizard", role: "dispatcher", path: "/bookings/new", ready: { role: "heading", name: /book/i } },
  { name: "jobs", role: "owner", path: "/jobs", ready: { role: "heading", name: "Jobs" } },
  { name: "customers", role: "owner", path: "/customers", ready: { role: "heading", name: "Customers" } },
  { name: "technician-schedule", role: "employee", path: "/schedule", ready: { role: "heading", name: /schedule/i } },
];

async function sessionCookies(role) {
  const api = await request.newContext({ baseURL: BASE_URL });
  const response = await api.post("/api/auth/login", {
    data: { email: `${role}@serviceflow.demo`, password: PASSWORD },
  });
  if (!response.ok()) throw new Error(`sign-in as ${role} failed: ${response.status()} ${await response.text()}`);
  const { cookies } = await api.storageState();
  await api.dispose();
  return cookies;
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const sessions = new Map();

for (const shot of SHOTS) {
  const context = await browser.newContext({
    baseURL: BASE_URL,
    viewport: { width: WIDTH, height: HEIGHT },
    colorScheme: "light",
    deviceScaleFactor: 2,
  });
  if (shot.role) {
    if (!sessions.has(shot.role)) sessions.set(shot.role, await sessionCookies(shot.role));
    await context.addCookies(sessions.get(shot.role));
  }
  const page = await context.newPage();
  await page.goto(shot.path);
  await page.getByRole(shot.ready.role, { name: shot.ready.name, level: 1 }).first().waitFor();
  await page.waitForLoadState("networkidle");
  const file = `${OUT}/${shot.name}-${WIDTH}.png`.replace(/\/+/g, "/");
  await page.screenshot({ path: file });
  console.log(file);
  await context.close();
}

await browser.close();
