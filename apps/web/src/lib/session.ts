import { cookies } from "next/headers";

/**
 * The API session token lives in an httpOnly cookie, never in localStorage:
 * a token readable from JavaScript is a token any XSS can exfiltrate.
 * Browser code talks to the route handlers under /api, which attach it server-side.
 */
export const SESSION_COOKIE = "sf_session";
export const ORG_COOKIE = "sf_org";

export const API_BASE_URL =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function getSessionToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

export async function getActiveOrganizationId(): Promise<string | null> {
  const store = await cookies();
  return store.get(ORG_COOKIE)?.value ?? null;
}

export function sessionCookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}
