"use client";

import { CalendarPlus, ClipboardList, Clock } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDuration, formatPrice, formatRelative, formatWindow } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking } from "@/lib/types";

const TABS = [
  { label: "Upcoming", value: "upcoming" },
  { label: "Past", value: "past" },
] as const;

type Tab = (typeof TABS)[number]["value"];

export function CustomerBookingsClient({ timeZone }: { timeZone: string }) {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [page, setPage] = useState(1);
  const [cancelling, setCancelling] = useState<Booking | null>(null);

  const params = { timeframe: tab, page, page_size: 10 };
  const query = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  const cancel = useResourceMutation<Booking, Booking>(
    (booking) =>
      apiFetchData<Booking>(`bookings/${booking.id}/cancel`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    { invalidate: [queryKeys.bookings.all], successMessage: "Booking cancelled" },
  );

  function changeTab(next: Tab) {
    setTab(next);
    setPage(1);
  }

  const bookings = query.data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="My bookings"
        description="Your upcoming appointments and service history."
        action={
          <Button render={<Link href="/bookings/new" />}>
            <CalendarPlus className="size-4" aria-hidden />
            Book a service
          </Button>
        }
      />

      <div role="group" aria-label="Filter bookings" className="flex w-fit rounded-lg border p-0.5">
        {TABS.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={tab === option.value ? "secondary" : "ghost"}
            aria-pressed={tab === option.value}
            onClick={() => changeTab(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>

      {query.isPending ? (
        <div className="grid gap-4">
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
            title={tab === "upcoming" ? "No upcoming appointments" : "No past appointments"}
            description={
              tab === "upcoming"
                ? "Book a service and it will show up here once you've requested it."
                : "Completed and cancelled appointments will appear here."
            }
            action={
              tab === "upcoming" ? (
                <Button size="sm" render={<Link href="/bookings/new" />}>
                  <CalendarPlus className="size-4" aria-hidden />
                  Book a service
                </Button>
              ) : null
            }
          />
        </Card>
      ) : null}

      <ul className="space-y-4">
        {bookings.map((booking) => (
          <li key={booking.id}>
            <Card className="p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-medium">{booking.service.name}</h2>
                    <BookingStatusBadge status={booking.status} />
                    {booking.job ? <JobStatusBadge status={booking.job.status} /> : null}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {formatWindow(booking.requested_start, booking.requested_end, timeZone)}
                    {tab === "upcoming" ? ` · ${formatRelative(booking.requested_start)}` : ""}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {booking.vehicle.display_name}
                    {booking.vehicle.license_plate ? ` · ${booking.vehicle.license_plate}` : ""}
                  </p>
                  {booking.job ? (
                    <p className="text-sm">
                      Technician:{" "}
                      <span className="font-medium">{booking.job.employee_name}</span>
                    </p>
                  ) : null}
                  {booking.customer_notes ? (
                    <p className="pt-1 text-sm text-muted-foreground">
                      <span className="font-medium text-foreground">Your note:</span>{" "}
                      {booking.customer_notes}
                    </p>
                  ) : null}
                </div>

                <div className="flex shrink-0 flex-col items-start gap-2 sm:items-end">
                  <p className="font-medium tabular-nums">
                    {formatPrice(booking.service.base_price)}
                  </p>
                  <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                    <Clock className="size-3.5" aria-hidden />
                    {formatDuration(booking.service.duration_minutes)}
                  </p>
                  {booking.status === "PENDING" || booking.status === "CONFIRMED" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={cancel.isPending}
                      onClick={() => setCancelling(booking)}
                    >
                      Cancel
                    </Button>
                  ) : null}
                </div>
              </div>
            </Card>
          </li>
        ))}
      </ul>

      {query.data ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="bookings" />
      ) : null}

      <ConfirmDialog
        open={cancelling !== null}
        onOpenChange={(open) => !open && setCancelling(null)}
        title="Cancel this booking?"
        description={
          cancelling?.job
            ? "Your appointment and the assigned technician's job will both be cancelled. You'll need to book again if you change your mind."
            : "Your request will be withdrawn. You'll need to book again if you change your mind."
        }
        confirmLabel="Cancel booking"
        pendingLabel="Cancelling..."
        onConfirm={async () => {
          if (cancelling) await cancel.mutateAsync(cancelling);
        }}
      />
    </div>
  );
}
