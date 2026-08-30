import type { ApiErrorBody } from "@/lib/types";

/** An API failure carrying the server's error code, for UI that reacts per code. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  readonly details?: Record<string, unknown>;
  /** Seconds to wait before retrying, from a rate-limited response. */
  readonly retryAfter?: number;

  constructor(status: number, body: ApiErrorBody, retryAfter?: number) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
    this.details = body.details;
    this.retryAfter = retryAfter;
  }
}

/**
 * A key that identifies one booking attempt, not one click.
 *
 * The server stores it, so replaying the same key with the same payload returns
 * the original booking instead of creating a second one - which is what makes a
 * double submit, a lost response or a refresh mid-request safe. Disabling the
 * button is a nicety; this is the actual guarantee.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `key-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

const FALLBACK: ApiErrorBody = {
  code: "INTERNAL_ERROR",
  message: "Something went wrong. Please try again.",
};

/** Browser-side API call. Goes through /api/proxy so the token stays server-side. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = path.startsWith("/api/") ? path : `/api/proxy/${path.replace(/^\//, "")}`;

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(503, {
      code: "DEPENDENCY_UNAVAILABLE",
      message: "We couldn't reach the server. Check your connection and try again.",
    });
  }

  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? (JSON.parse(text) as unknown) : null;
  } catch {
    // A gateway or proxy answered with something that is not our envelope.
    // Whatever it says is not for the user to read.
    throw new ApiError(response.status || 502, FALLBACK);
  }

  if (!response.ok) {
    const error = (body as { error?: ApiErrorBody } | null)?.error ?? FALLBACK;
    const header = response.headers.get("Retry-After");
    const retryAfter = header && /^\d+$/.test(header) ? Number(header) : undefined;
    throw new ApiError(response.status, error, retryAfter);
  }
  return body as T;
}

/** Unwraps the `{ data: ... }` envelope the API returns for single resources. */
export async function apiFetchData<T>(path: string, init?: RequestInit): Promise<T> {
  const body = await apiFetch<{ data: T }>(path, init);
  return body.data;
}
