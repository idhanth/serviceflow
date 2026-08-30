"use client";

import { WifiOff } from "lucide-react";

import { useRealtimeStatus } from "@/components/providers/realtime-provider";

/**
 * Shown only once reconnection has really stopped working.
 *
 * A transient drop is normal - EventSource retries by itself and the app keeps
 * refetching - so flashing a warning on every blip would be noise. The wording
 * says what it means for the reader: the page is still correct, just not live.
 */
export function ConnectionStatus() {
  const status = useRealtimeStatus();
  if (status !== "offline") return null;

  return (
    <span
      role="status"
      className="flex items-center gap-1.5 rounded-full border border-amber-600/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-700 dark:border-amber-400/30 dark:text-amber-300"
    >
      <WifiOff className="size-3.5" aria-hidden />
      Live updates paused — still refreshing
    </span>
  );
}
