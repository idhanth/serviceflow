"use client";

import { ClipboardList } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDayLabel, formatPrice, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking, BookingStatus } from "@/lib/types";

import { BookingReviewSheet } from "./booking-review-sheet";

const COLUMNS = 6;
const FILTERS = [
  { label: "Pending", value: "PENDING" },
  { label: "Confirmed", value: "CONFIRMED" },
  { label: "Declined", value: "REJECTED" },
  { label: "Cancelled", value: "CANCELLED" },
  { label: "All", value: "all" },
] as const;

type Filter = (typeof FILTERS)[number]["value"];

export function AdminBookingsClient({ timeZone }: { timeZone: string }) {
  const [filter, setFilter] = useState<Filter>("PENDING");
  const [page, setPage] = useState(1);
  const [reviewing, setReviewing] = useState<Booking | null>(null);

  const params = {
    page,
    page_size: 12,
    status: filter === "all" ? undefined : (filter as BookingStatus),
  };
  const query = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  const bookings = query.data?.data ?? [];
  const showEmpty = query.isSuccess && bookings.length === 0;

  // Keep the open sheet in step with refetched data after a mutation.
  const active = reviewing
    ? (bookings.find((booking) => booking.id === reviewing.id) ?? reviewing)
    : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bookings"
        description="Review requests, assign a technician, and confirm the work."
      />

      <div
        role="group"
        aria-label="Filter by status"
        className="flex w-full overflow-x-auto rounded-lg border p-0.5 sm:w-fit"
      >
        {FILTERS.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={filter === option.value ? "secondary" : "ghost"}
            aria-pressed={filter === option.value}
            className="shrink-0"
            onClick={() => changeFilter(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>

      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[160px]">Customer</TableHead>
                <TableHead className="min-w-[150px]">Service</TableHead>
                <TableHead className="min-w-[150px]">Vehicle</TableHead>
                <TableHead className="min-w-[150px]">Requested</TableHead>
                <TableHead className="min-w-[150px]">Status</TableHead>
                <TableHead className="text-right">Price</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={COLUMNS} /> : null}

              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}

              {showEmpty ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <EmptyState
                      icon={ClipboardList}
                      title={
                        filter === "PENDING"
                          ? "Nothing waiting on you"
                          : "No bookings match this filter"
                      }
                      description={
                        filter === "PENDING"
                          ? "New booking requests will appear here for review."
                          : "Try a different status filter."
                      }
                      action={
                        filter === "PENDING" ? null : (
                          <Button variant="outline" size="sm" onClick={() => changeFilter("PENDING")}>
                            Back to pending
                          </Button>
                        )
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {bookings.map((booking) => (
                <TableRow
                  key={booking.id}
                  className="cursor-pointer"
                  onClick={() => setReviewing(booking)}
                >
                  <TableCell className="font-medium">
                    {booking.customer?.full_name ?? "—"}
                  </TableCell>
                  <TableCell>{booking.service.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {booking.vehicle.display_name}
                  </TableCell>
                  <TableCell>
                    <div>{formatDayLabel(booking.requested_start, timeZone)}</div>
                    <div className="text-sm text-muted-foreground">
                      {formatTime(booking.requested_start, timeZone)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1.5">
                      <BookingStatusBadge status={booking.status} />
                      {booking.job ? <JobStatusBadge status={booking.job.status} /> : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatPrice(booking.service.base_price)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      {query.data ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="bookings" />
      ) : null}

      <BookingReviewSheet
        booking={active}
        timeZone={timeZone}
        onOpenChange={(open) => !open && setReviewing(null)}
      />
    </div>
  );
}
