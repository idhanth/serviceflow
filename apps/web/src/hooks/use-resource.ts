"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiFetch, ApiError } from "@/lib/api-client";
import type { Paged } from "@/lib/types";

export function toQueryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

/** A paginated collection request against the API. */
export function usePagedResource<T>(
  key: readonly unknown[],
  path: string,
  params: Record<string, unknown>,
  options: { enabled?: boolean } = {},
) {
  return useQuery<Paged<T>, ApiError>({
    queryKey: key,
    queryFn: () => apiFetch<Paged<T>>(`${path}${toQueryString(params)}`),
    placeholderData: (previous) => previous, // keeps the table steady while paging
    enabled: options.enabled ?? true,
  });
}

/**
 * A mutation that reports failure with the server's own message and refreshes
 * the affected lists. Every mutating form in the app goes through this so error
 * and success handling cannot drift between pages (PRD 57).
 */
export function useResourceMutation<TInput, TOutput>(
  mutate: (input: TInput) => Promise<TOutput>,
  {
    invalidate,
    successMessage,
    fallbackError = "Something went wrong. Please try again.",
  }: {
    invalidate: readonly (readonly unknown[])[];
    successMessage: string | ((result: TOutput) => string);
    fallbackError?: string;
  },
) {
  const queryClient = useQueryClient();

  return useMutation<TOutput, ApiError, TInput>({
    mutationFn: mutate,
    onSuccess: async (result) => {
      await Promise.all(
        invalidate.map((key) => queryClient.invalidateQueries({ queryKey: key })),
      );
      toast.success(
        typeof successMessage === "function" ? successMessage(result) : successMessage,
      );
    },
    onError: (error) => {
      toast.error(errorMessage(error, fallbackError), errorDetail(error));
    },
  });
}

/**
 * What to show the user for a failed mutation.
 *
 * The server's message is written for people and is used as-is, except where a
 * code implies something the message alone cannot say - how long to wait, or
 * that the form has drifted from an attempt already in flight.
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  switch (error.code) {
    case "RATE_LIMITED":
      return error.retryAfter
        ? `Too many attempts. Try again in ${describeWait(error.retryAfter)}.`
        : error.message;
    case "IDEMPOTENCY_CONFLICT":
      return "This looks like a changed version of a request already sent. Reload the page and check before trying again.";
    default:
      return error.message || fallback;
  }
}

/** A request id is worth showing only when there is nothing else the user can do. */
function errorDetail(error: unknown): { description?: string } | undefined {
  if (!(error instanceof ApiError)) return undefined;
  if (error.code !== "INTERNAL_ERROR" || !error.requestId) return undefined;
  return { description: `Reference: ${error.requestId}` };
}

function describeWait(seconds: number): string {
  if (seconds < 60) return `${seconds} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "a minute" : `${minutes} minutes`;
}

/** Pulls per-field messages out of a VALIDATION_FAILED response, for form display. */
export function fieldErrorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const fields = error.details?.fields;
  if (!fields || typeof fields !== "object") return {};
  return Object.fromEntries(
    Object.entries(fields as Record<string, unknown>).map(([key, value]) => [key, String(value)]),
  );
}
