import { request } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { ACCOUNTS, BASE_URL, DEMO_PASSWORD, RUN_STATE, storageFor, type Role } from "./config";

/**
 * Signs every role in once, through the app's own login route, and parks the
 * cookies. Sign-in is rate limited and the suite leaves the limiter on, so specs
 * reuse these sessions instead of authenticating per test. Signing in through
 * the form itself is covered by 01-auth-and-navigation.
 */
export default async function globalSetup() {
  const probe = await request.newContext({ baseURL: BASE_URL });
  const up = await probe.get("/login").catch(() => null);
  if (!up || !up.ok()) {
    throw new Error(`The web app is not answering at ${BASE_URL}. Start the stack first (docker compose up).`);
  }
  await probe.dispose();

  for (const role of Object.keys(ACCOUNTS) as Role[]) {
    const api = await request.newContext({ baseURL: BASE_URL });
    const response = await api.post("/api/auth/login", {
      data: { email: ACCOUNTS[role], password: DEMO_PASSWORD },
    });
    if (!response.ok()) {
      throw new Error(`Signing in as ${role} failed: ${response.status()} ${await response.text()}`);
    }
    mkdirSync(dirname(storageFor(role)), { recursive: true });
    await api.storageState({ path: storageFor(role) });
    await api.dispose();
  }

  mkdirSync(dirname(RUN_STATE), { recursive: true });
  writeFileSync(RUN_STATE, JSON.stringify({ runId: Date.now().toString(36) }, null, 2));
}
