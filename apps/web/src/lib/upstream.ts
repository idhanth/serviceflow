import type { NextRequest } from "next/server";

/**
 * Headers every server-side call to the API carries.
 *
 * Two things travel with it that the API cannot work out for itself:
 *
 * **The caller's address.** Every browser request reaches the API through this
 * application, so without help the API sees one address - this server's - and
 * counts every visitor's sign-up attempt against a single bucket. Five people
 * would exhaust the hourly signup allowance for everyone. The address the edge
 * observed is prepended to X-Forwarded-For, and the API is told (via
 * TRUSTED_PROXY_COUNT) how many hops to skip to find it.
 *
 * **A shared secret.** Because the API trusts that forwarded address, the API
 * must not be reachable except through here. The reverse proxy in front of it
 * rejects anything without this token, so a forged X-Forwarded-For sent straight
 * at the API never arrives.
 */
const PROXY_TOKEN = process.env.API_PROXY_TOKEN;

export function forwardedFor(request: NextRequest | Request): string | null {
  // Vercel and most edges set this; the left-most entry is the real client.
  const chain = request.headers.get("x-forwarded-for");
  if (chain) {
    const client = chain.split(",")[0]?.trim();
    if (client) return client;
  }
  const real = request.headers.get("x-real-ip");
  return real?.trim() ?? null;
}

export function upstreamHeaders(
  request: NextRequest | Request,
  init: Record<string, string>,
): Headers {
  const headers = new Headers(init);
  const client = forwardedFor(request);
  if (client) headers.set("X-Forwarded-For", client);
  if (PROXY_TOKEN) headers.set("X-Proxy-Token", PROXY_TOKEN);
  return headers;
}
