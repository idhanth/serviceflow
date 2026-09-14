"use client";

import { CalendarPlus, ClipboardList, MapPin, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { Segmented } from "@/components/data/segmented";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDuration, formatPrice, formatRelative, formatWindow } from "@/lib/format";
import { OPERATIONS_KEYS, queryKeys } from "@/lib/query-keys";
import type { Booking } from "@/lib/types";

const TABS = [
  { label: "Upcoming", value: "upcoming" },
  { label: "History", value: "past" },
] as const;

type Tab = (typeof TABS)[number]["value"];

/** A customer's own appointments and service history - nobody else's, by construction. */
export function CustomerBookingsClient({ timeZone }: { timeZone: string }) {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [page, setPage] = useState(1);
  const [cancelling, setCancelling] = useState<Booking | null>(null);

  const params = { timeframe: tab, page, page_size: 10 };
  const query = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  const cancel = useResourceMutation<Booking, Booking>(
    (booking) =>
      apiFetchData<Booking>(`bookings/${booking.id}/cancel`, { method: "POST", body: JSON.stringify({}) }),
    { invalidate: OPERATIONS_KEYS, successMessage: "Booking cancelled" },
  );

  const bookings = query.data?.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="My Bookings"
        description="Your upcoming appointments and your service history."
        action={
          <Button size="sm" render={<Link href="/bookings/new" />}>
            <CalendarPlus className="size-3.5" aria-hidden />
            Book service
          </Button>
        }
      />

      <Toolbar>
        <Segmented
          label="Show"
          value={tab}
          onChange={(next) => {
            setTab(next);
            setPage(1);
          }}
          options={TABS}
        />
      </Toolbar>

      {query.isPending ? (
        <div className="grid gap-3">
          <CardSkeletons count={3} />
        </div>
      ) : null}

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : null}

      {query.isSuccess && bookings.length === 0 ? (
        <Card>
          <EmptyState
            icon={ClipboardList}
            title={tab === "upcoming" ? "No upcoming appointments" : "No service history yet"}
            description={
              tab === "upcoming"
                ? "Book a service and it will show up here straight away."
                : "Completed and cancelled appointments will appear here."
            }
            action={
              tab === "upcoming" ? (
                <Button size="sm" render={<Link href="/bookings/new" />}>
                  <CalendarPlus className="size-3.5" aria-hidden />
                  Book service
                </Button>
              ) : null
            }
          />
        </Card>
      ) : null}

      <ul className="space-y-3">
        {bookings.map((booking) => {
          const working = booking.job && (booking.job.status === "IN_PROGRESS" || booking.job.status === "COMPLETED");
          return (
            <li key={booking.id}>
              <Card className="p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-[15px] font-medium">
                        <Link href={`/bookings/${booking.id}`} className="focus-ring hover:underline">
                          {booking.service.name}
                        </Link>
                      </h2>
                      {/* One state, in the customer's language: the job's status only
                          takes over once work has actually started. */}
                      {working && booking.job ? (
                        <JobStatusBadge status={booking.job.status} />
                      ) : booking.status === "PENDING" ? (
                        <span className="text-[13px] text-muted-foreground">Requested · awaiting a technician</span>
                      ) : (
                        <BookingStatusBadge status={booking.status} />
                      )}
                    </div>
                    <p className="text-[13px] text-muted-foreground">
                      {formatWindow(booking.requested_start, booking.requested_end, timeZone)}
                      {tab === "upcoming" ? ` · ${formatRelative(booking.requested_start)}` : ""}
                    </p>
                    {booking.job?.employee_name ? (
                      <p className="flex items-center gap-1.5 text-[13px]">
                        <UserRound className="size-3.5 text-muted-foreground" aria-hidden />
                        {booking.job.employee_name}
                      </p>
                    ) : null}
                    {booking.customer_notes ? (
                      <p className="flex items-start gap-1.5 text-[13px] text-muted-foreground">
                        <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                        {booking.customer_notes}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex shrink-0 flex-col items-start gap-3 sm:items-end">
                    <div className="space-y-0.5 sm:text-right">
                      <p className="text-[15px] font-medium tabular-nums">{formatPrice(booking.service.base_price)}</p>
                      <p className="text-[12px] text-muted-foreground">{formatDuration(booking.service.duration_minutes)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {(booking.status === "PENDING" || booking.status === "CONFIRMED") && !working ? (
                        <Button variant="ghost" size="sm" disabled={cancel.isPending} onClick={() => setCancelling(booking)}>
                          Cancel
                        </Button>
                      ) : null}
                      <Button variant="outline" size="sm" render={<Link href={`/bookings/${booking.id}`} />}>
                        Details
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            </li>
          );
        })}
      </ul>

      {query.data && query.data.meta.total > 0 ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="bookings" />
      ) : null}

      <ConfirmDialog
        open={cancelling !== null}
        onOpenChange={(open) => !open && setCancelling(null)}
        title="Cancel this appointment?"
        description="Your appointment is cancelled and the technician is taken off it. You'll need to book again if you change your mind."
        confirmLabel="Cancel appointment"
        pendingLabel="Cancelling..."
        onConfirm={async () => {
          if (cancelling) await cancel.mutateAsync(cancelling);
        }}
      />
    </div>
  );
}
