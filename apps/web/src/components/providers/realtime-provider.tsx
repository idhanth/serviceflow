"use client";

import { createContext, useContext } from "react";

import { type RealtimeStatus, useRealtime } from "@/hooks/use-realtime";

const RealtimeContext = createContext<RealtimeStatus>("connecting");

/**
 * One event stream per tab, shared by everything that cares.
 *
 * Mounted inside the app shell rather than the root layout so it only opens for
 * signed-in pages - the sign-in screen has nothing to listen to.
 */
export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const status = useRealtime();
  return <RealtimeContext value={status}>{children}</RealtimeContext>;
}

export function useRealtimeStatus(): RealtimeStatus {
  return useContext(RealtimeContext);
}
