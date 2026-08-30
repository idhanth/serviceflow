import { NextResponse } from "next/server";

import {
  API_BASE_URL,
  getActiveOrganizationId,
  getSessionToken,
} from "@/lib/session";

/**
 * Server-side pass-through to the API. Browser code calls /api/proxy/... and the
 * session token is attached here, so it is never exposed to client JavaScript.
 * Authorization itself is still decided by the API (PRD 6, 61).
 */
async function forward(request: Request, path: string[]) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json(
      { error: { code: "UNAUTHORIZED", message: "You need to sign in to continue." } },
      { status: 401 },
    );
  }

  const organizationId = await getActiveOrganizationId();
  const search = new URL(request.url).search;
  const target = `${API_BASE_URL}/api/v1/${path.join("/")}${search}`;

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${token}`);
  if (organizationId) headers.set("X-Organization-Id", organizationId);

  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const idempotencyKey = request.headers.get("idempotency-key");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);

  const hasBody = !["GET", "HEAD"].includes(request.method);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
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

  const responseBody = await upstream.text();
  const responseHeaders = new Headers({
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  });
  // Pass through what the client needs to react to a failure: how long to wait,
  // and the id to quote when reporting it. Nothing else from upstream is copied.
  for (const name of ["retry-after", "x-request-id", "idempotent-replay"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new NextResponse(responseBody || null, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, { params }: Context) {
  return forward(request, (await params).path);
}
export async function POST(request: Request, { params }: Context) {
  return forward(request, (await params).path);
}
export async function PATCH(request: Request, { params }: Context) {
  return forward(request, (await params).path);
}
export async function DELETE(request: Request, { params }: Context) {
  return forward(request, (await params).path);
}
