import type { ApiErrorBody } from "@/lib/types";

/** An API failure carrying the server's error code, for UI that reacts per code. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
    this.details = body.details;
  }
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
  const body = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    const error = (body as { error?: ApiErrorBody } | null)?.error ?? FALLBACK;
    throw new ApiError(response.status, error);
  }
  return body as T;
}

/** Unwraps the `{ data: ... }` envelope the API returns for single resources. */
export async function apiFetchData<T>(path: string, init?: RequestInit): Promise<T> {
  const body = await apiFetch<{ data: T }>(path, init);
  return body.data;
}
