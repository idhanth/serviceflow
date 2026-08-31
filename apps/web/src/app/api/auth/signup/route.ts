import { NextResponse } from "next/server";

import { API_BASE_URL, ORG_COOKIE, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";
import { upstreamHeaders } from "@/lib/upstream";

/** Registers a customer and stores the returned session in an httpOnly cookie. */
export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: { code: "VALIDATION_FAILED", message: "Fill in the form to continue." } },
      { status: 422 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/v1/auth/signup`, {
      method: "POST",
      // The caller's address travels with it: these are the two endpoints the
      // limiter protects by address, and without it every visitor would share
      // one bucket.
      headers: upstreamHeaders(request, { "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      {
        error: {
          code: "DEPENDENCY_UNAVAILABLE",
          message: "We couldn't reach the server. Please try again in a moment.",
        },
      },
      { status: 503 },
    );
  }

  const body = await upstream.json().catch(() => null);
  if (!upstream.ok || !body?.access_token) {
    return NextResponse.json(
      body ?? { error: { code: "INTERNAL_ERROR", message: "We couldn't create your account." } },
      { status: upstream.status },
    );
  }

  const response = NextResponse.json({ user: body.user });
  response.cookies.set(SESSION_COOKIE, body.access_token, sessionCookieOptions(body.expires_in));
  const firstOrg = body.user?.memberships?.[0]?.organization_id;
  if (firstOrg) {
    response.cookies.set(ORG_COOKIE, firstOrg, sessionCookieOptions(body.expires_in));
  }
  return response;
}
