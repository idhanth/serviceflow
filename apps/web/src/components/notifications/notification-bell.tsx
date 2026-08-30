"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { AppNotification, Paged } from "@/lib/types";
import { cn } from "@/lib/utils";

const LIST_PARAMS = { page: 1, page_size: 15 };

export function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  const unread = useQuery<{ data: { unread: number } }, ApiError>({
    queryKey: queryKeys.notifications.unread,
    queryFn: () => apiFetch<{ data: { unread: number } }>("notifications/unread-count"),
    // Polled, not pushed: realtime arrives in phase 6.
    refetchInterval: 60_000,
  });

  const list = useQuery<Paged<AppNotification>, ApiError>({
    queryKey: queryKeys.notifications.list(LIST_PARAMS),
    queryFn: () =>
      apiFetch<Paged<AppNotification>>(
        `notifications?page=${LIST_PARAMS.page}&page_size=${LIST_PARAMS.page_size}`,
      ),
    enabled: open,
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
  }

  async function openAndRead(notification: AppNotification) {
    if (!notification.unread) return;
    try {
      await apiFetch(`notifications/${notification.id}/read`, { method: "POST" });
      refresh();
    } catch {
      // Reading is best-effort; the badge corrects itself on the next poll.
    }
  }

  async function markAll() {
    setMarkingAll(true);
    try {
      await apiFetch("notifications/read-all", { method: "POST" });
      refresh();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Couldn't mark those as read.",
      );
    } finally {
      setMarkingAll(false);
    }
  }

  const count = unread.data?.data.unread ?? 0;
  const rows = list.data?.data ?? [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative"
            aria-label={count > 0 ? `Notifications, ${count} unread` : "Notifications"}
          />
        }
      >
        <Bell className="size-5" aria-hidden />
        {count > 0 ? (
          <span
            aria-hidden
            className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-4 text-primary-foreground"
          >
            {count > 9 ? "9+" : count}
          </span>
        ) : null}
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[22rem] p-0">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-sm font-medium">Notifications</span>
          {count > 0 ? (
            <Button variant="ghost" size="sm" disabled={markingAll} onClick={markAll}>
              {markingAll ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <CheckCheck className="size-3.5" aria-hidden />
              )}
              Mark all read
            </Button>
          ) : null}
        </div>
        <Separator />

        <div className="max-h-[26rem] overflow-y-auto">
          {list.isPending ? (
            <div className="space-y-2 p-3">
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-14 w-full rounded-lg" />
              ))}
            </div>
          ) : null}

          {list.isError ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} />
          ) : null}

          {list.isSuccess && rows.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="Nothing yet"
              description="Updates about your bookings will show up here."
            />
          ) : null}

          <ul>
            {rows.map((notification) => {
              const bookingId = notification.payload?.booking_id;
              const body = (
                <>
                  <span className="flex items-start gap-2">
                    <span
                      aria-hidden
                      className={cn(
                        "mt-1.5 size-1.5 shrink-0 rounded-full",
                        notification.unread ? "bg-primary" : "bg-transparent",
                      )}
                    />
                    <span className="min-w-0">
                      <span
                        className={cn(
                          "block text-sm",
                          notification.unread ? "font-medium" : "text-muted-foreground",
                        )}
                      >
                        {notification.subject}
                      </span>
                      <span className="block text-sm text-muted-foreground">
                        {notification.body}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {formatRelative(notification.created_at)}
                      </span>
                    </span>
                  </span>
                </>
              );

              return (
                <li key={notification.id} className="border-b last:border-b-0">
                  {bookingId ? (
                    <Link
                      href={`/bookings/${bookingId}`}
                      onClick={() => {
                        void openAndRead(notification);
                        setOpen(false);
                      }}
                      className="block px-3 py-2.5 transition-colors duration-150 hover:bg-accent/50"
                    >
                      {body}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void openAndRead(notification)}
                      className="block w-full px-3 py-2.5 text-left transition-colors duration-150 hover:bg-accent/50"
                    >
                      {body}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </PopoverContent>
    </Popover>
  );
}
