"use client";

import { ArrowRight, Car } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { DataPanel } from "@/components/data/data-panel";
import { SectionHeader } from "@/components/data/page-header";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDayLabel, formatPrice, formatTime, isPast } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking, Vehicle } from "@/lib/types";

/**
 * What a customer wants to know: when is my car booked in, and what happened
 * last time. No metrics - a customer does not have a dashboard, they have an
 * appointment.
 */
export function CustomerOverview({ timeZone }: { timeZone: string }) {
  const params = { page: 1, page_size: 50 };
  const bookings = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  const vehicleParams = { page: 1, page_size: 20 };
  const vehicles = usePagedResource<Vehicle>(
    queryKeys.vehicles.list(vehicleParams),
    "vehicles",
    vehicleParams,
  );

  const { next, upcoming, past } = useMemo(() => {
    const all = bookings.data?.data ?? [];
    const open = all
      .filter((booking) => !isPast(booking.requested_start) && booking.status !== "CANCELLED")
      .sort((a, b) => a.requested_start.localeCompare(b.requested_start));
    const history = all
      .filter((booking) => isPast(booking.requested_start))
      .sort((a, b) => b.requested_start.localeCompare(a.requested_start))
      .slice(0, 5);
    return { next: open[0] ?? null, upcoming: open.slice(1, 4), past: history };
  }, [bookings.data]);

  if (bookings.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (bookings.isError) {
    return (
      <DataPanel>
        <ErrorState error={bookings.error} onRetry={() => bookings.refetch()} />
      </DataPanel>
    );
  }

  return (
    <div className="space-y-6">
      {/* The next appointment is the whole point of the page, so it is the only
          thing on screen with any prominence. */}
      <section className="space-y-3">
        <SectionHeader title="Next appointment" />

        {next ? (
          <DataPanel className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-6">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2.5">
                  <h3 className="text-[17px] font-semibold">{next.service.name}</h3>
                  {next.job ? (
                    <JobStatusBadge status={next.job.status} variant="chip" />
                  ) : (
                    <BookingStatusBadge status={next.status} variant="chip" />
                  )}
                </div>
                <p className="text-[13px] text-muted-foreground">{next.vehicle.display_name}</p>
              </div>

              <dl className="flex flex-wrap gap-x-10 gap-y-3">
                <div>
                  <dt className="text-[12px] text-muted-foreground">Date</dt>
                  <dd className="text-[13px] font-medium">
                    {formatDayLabel(next.requested_start, timeZone)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[12px] text-muted-foreground">Time</dt>
                  <dd className="text-[13px] font-medium tabular-nums">
                    {formatTime(next.requested_start, timeZone)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[12px] text-muted-foreground">Price</dt>
                  <dd className="text-[13px] font-medium tabular-nums">
                    {formatPrice(next.service.base_price)}
                  </dd>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  render={<Link href={`/bookings/${next.id}`} />}
                >
                  View
                  <ArrowRight className="size-3.5" aria-hidden />
                </Button>
              </dl>
            </div>
          </DataPanel>
        ) : (
          <DataPanel>
            <EmptyState
              icon={Car}
              title="No appointment booked"
              description={
                (vehicles.data?.meta.total ?? 0) === 0
                  ? "Add your vehicle, then choose a service and a time that suits you."
                  : "Choose a service and a time that suits you."
              }
              action={
                <Button
                  size="sm"
                  render={
                    <Link
                      href={(vehicles.data?.meta.total ?? 0) === 0 ? "/vehicles" : "/bookings/new"}
                    />
                  }
                >
                  {(vehicles.data?.meta.total ?? 0) === 0 ? "Add a vehicle" : "Book a service"}
                </Button>
              }
            />
          </DataPanel>
        )}
      </section>

      {upcoming.length > 0 ? (
        <section className="space-y-3">
          <SectionHeader title="Also booked" />
          <DataPanel>
            <div className="divide-y">
              {upcoming.map((booking) => (
                <Link
                  key={booking.id}
                  href={`/bookings/${booking.id}`}
                  className="focus-ring flex items-center justify-between gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium">
                      {booking.service.name}
                    </span>
                    <span className="block truncate text-[12px] text-muted-foreground">
                      {formatDayLabel(booking.requested_start, timeZone)} ·{" "}
                      {formatTime(booking.requested_start, timeZone)}
                    </span>
                  </span>
                  <BookingStatusBadge status={booking.status} />
                </Link>
              ))}
            </div>
          </DataPanel>
        </section>
      ) : null}

      {past.length > 0 ? (
        <section className="space-y-3">
          <SectionHeader
            title="Recent visits"
            action={
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/bookings" />}>
                All bookings
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            }
          />
          <DataPanel>
            <div className="divide-y">
              {past.map((booking) => (
                <Link
                  key={booking.id}
                  href={`/bookings/${booking.id}`}
                  className="focus-ring flex items-center justify-between gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[13px]">{booking.service.name}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">
                      {booking.vehicle.display_name}
                    </span>
                  </span>
                  <span className="shrink-0 text-[12px] text-muted-foreground tabular-nums">
                    {formatDayLabel(booking.requested_start, timeZone)}
                  </span>
                </Link>
              ))}
            </div>
          </DataPanel>
        </section>
      ) : null}
    </div>
  );
}
