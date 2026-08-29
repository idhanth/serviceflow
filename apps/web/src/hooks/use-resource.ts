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
      toast.error(error instanceof ApiError ? error.message : fallbackError);
    },
  });
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
