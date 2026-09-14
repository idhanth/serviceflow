"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { queryKeys } from "@/lib/query-keys";

/** The envelope the API publishes. Deliberately small - no record content. */
export interface RealtimeEvent {
  type: string;
  resource: "notification" | "booking" | "job";
  resource_id: string;
  organization_id: string;
  occurred_at: string;
}

export type RealtimeStatus = "connecting" | "live" | "offline";

/** Only surface trouble once reconnecting has genuinely stopped working. */
const FAILURES_BEFORE_OFFLINE = 3;
const FALLBACK_POLL_MS = 60_000;
const LIVE_POLL_MS = 5 * 60_000;

/**
 * Subscribes to the server's event stream and turns each event into a cache
 * invalidation.
 *
 * The events carry no data - they name what changed, and TanStack Query refetches
 * it. That keeps one source of truth (the API) and makes a dropped event
 * harmless: the next refetch is correct regardless. EventSource reconnects on
 * its own, and a periodic refetch stays configured as a floor, so nothing here
 * is required for the app to show current data.
 */
export function useRealtime(): RealtimeStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const failures = useRef(0);

  useEffect(() => {
    let source: EventSource | null = null;
    let closed = false;

    function connect() {
      if (closed) return;
      source = new EventSource("/api/events");

      source.onopen = () => {
        failures.current = 0;
        setStatus("live");
      };

      source.onmessage = (message) => {
        let event: RealtimeEvent;
        try {
          event = JSON.parse(message.data) as RealtimeEvent;
        } catch {
          return; // A malformed frame is not worth breaking the stream over.
        }

        // Duplicates are expected and harmless: invalidation is idempotent.
        switch (event.resource) {
          case "notification":
            void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
            break;
          case "booking":
            void queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.schedule.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all });
            break;
          case "job":
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.bookings.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.schedule.all });
            break;
        }
      };

      source.onerror = () => {
        source?.close();
        failures.current += 1;
        // Stay quiet through the first few blips; EventSource retries on its own
        // and a brief drop is not something to alarm anyone about.
        setStatus(failures.current >= FAILURES_BEFORE_OFFLINE ? "offline" : "connecting");

        const backoff = Math.min(1000 * 2 ** failures.current, 30_000);
        window.setTimeout(connect, backoff);
      };
    }

    connect();
    return () => {
      closed = true;
      source?.close();
    };
  }, [queryClient]);

  return status;
}

/** How often to refetch when realtime is not carrying the load. */
export function fallbackInterval(status: RealtimeStatus): number {
  return status === "live" ? LIVE_POLL_MS : FALLBACK_POLL_MS;
}
