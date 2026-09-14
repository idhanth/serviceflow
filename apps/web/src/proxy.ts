import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Keeps signed-out visitors off application routes. This is a redirect for UX
 * only - the API authorizes every request independently.
 */
export function proxy(request: NextRequest) {
  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const { pathname, search } = request.nextUrl;

  if (!hasSession) {
    const login = new URL("/login", request.url);
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  // Every authenticated route. The pages redirect on their own too, via
  // requireSession - this just avoids rendering one at all when signed out.
  matcher: [
    "/dashboard/:path*",
    "/bookings/:path*",
    "/jobs/:path*",
    "/schedule/:path*",
    "/availability/:path*",
    "/customers/:path*",
    "/employees/:path*",
    "/services/:path*",
    "/activity/:path*",
    "/settings/:path*",
    "/profile/:path*",
    "/platform/:path*",
  ],
};
