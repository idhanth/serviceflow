import {
  API_BASE_URL,
  getActiveOrganizationId,
  getSessionToken,
} from "@/lib/session";

/**
 * Streams the API's SSE feed to the browser.
 *
 * EventSource cannot send an Authorization header, which is why this proxy
 * exists: the browser connects here with its httpOnly cookie, and the token is
 * attached server-side exactly as it is for every other request. The alternative
 * - putting the JWT somewhere JavaScript can read it - would undo the phase 1
 * security model for the sake of one endpoint.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return new Response("unauthorized", { status: 401 });
  }

  const headers = new Headers({
    Authorization: `Bearer ${token}`,
    Accept: "text/event-stream",
  });
  const organizationId = await getActiveOrganizationId();
  if (organizationId) headers.set("X-Organization-Id", organizationId);

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/api/v1/events`, {
      headers,
      // Pass the client's disconnect through, so the API stops streaming when
      // the browser goes away.
      signal: request.signal,
      cache: "no-store",
    });
  } catch {
    return new Response("realtime unavailable", { status: 503 });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response("realtime unavailable", { status: upstream.status || 503 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
