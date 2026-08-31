"use client";

import { ClipboardList } from "lucide-react";
import { useState } from "react";

import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { MobileList, MobileRow } from "@/components/data/mobile-list";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { Segmented } from "@/components/data/segmented";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
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
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [reviewing, setReviewing] = useState<Booking | null>(null);

  const params = {
    page,
    page_size: 20,
    q,
    status: filter === "all" ? undefined : (filter as BookingStatus),
  };
  const query = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  // The pending count is the number an admin is actually managing, so it sits
  // on the filter itself rather than making them switch tabs to find it.
  const pendingParams = { page: 1, page_size: 1, status: "PENDING" as BookingStatus };
  const pending = usePagedResource<Booking>(
    queryKeys.bookings.list(pendingParams),
    "bookings",
    pendingParams,
  );

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  function search(next: string) {
    setQ(next);
    setPage(1);
  }

  const bookings = query.data?.data ?? [];
  const showEmpty = query.isSuccess && bookings.length === 0;

  // Keep the open sheet in step with refetched data after a mutation.
  const active = reviewing
    ? (bookings.find((booking) => booking.id === reviewing.id) ?? reviewing)
    : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Bookings"
        description="Requests from customers, waiting to be scheduled or already booked in."
      />

      <Toolbar className="justify-between">
        <Segmented
          label="Filter by status"
          value={filter}
          onChange={changeFilter}
          options={FILTERS.map((option) =>
            option.value === "PENDING"
              ? { ...option, count: pending.data?.meta.total }
              : option,
          )}
        />
        <SearchInput
          value={q}
          onChange={search}
          label="Search bookings"
          placeholder="Search bookings"
        />
      </Toolbar>

      <DataPanel>
        {/* Phones get the same records as a stacked list; see MobileList. */}
        <MobileList>
          {bookings.map((booking) => (
            <MobileRow
              key={booking.id}
              onClick={() => setReviewing(booking)}
              title={booking.customer?.full_name ?? "Unknown customer"}
              subtitle={`${booking.service.name} · ${booking.vehicle.display_name}`}
              trailing={
                <span className="text-[14px] font-medium tabular-nums">
                  {formatPrice(booking.service.base_price)}
                </span>
              }
              meta={
                <>
                  <span className="text-[12px] text-muted-foreground">
                    {formatDayLabel(booking.requested_start, timeZone)} ·{" "}
                    {formatTime(booking.requested_start, timeZone)}
                  </span>
                  {booking.job ? (
                    <JobStatusBadge status={booking.job.status} />
                  ) : (
                    <BookingStatusBadge status={booking.status} />
                  )}
                </>
              }
            />
          ))}
        </MobileList>

        <div className="hidden overflow-x-auto md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[190px]">Customer</TableHead>
                <TableHead className="min-w-[150px]">Service</TableHead>
                <TableHead className="min-w-[170px]">Requested</TableHead>
                <TableHead className="min-w-[130px]">Technician</TableHead>
                <TableHead className="min-w-[140px]">Status</TableHead>
                <TableHead className="min-w-[90px] text-right">Price</TableHead>
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
                    {/* The message has to match why it is empty: a search that
                        found nothing is a different situation from an empty
                        queue, and offering "back to pending" to someone who is
                        searching does not help them. */}
                    <EmptyState
                      icon={ClipboardList}
                      title={
                        q
                          ? `No bookings match “${q}”`
                          : filter === "PENDING"
                            ? "Nothing waiting on you"
                            : "No bookings with this status"
                      }
                      description={
                        q
                          ? "Try a different name, service or vehicle."
                          : filter === "PENDING"
                            ? "New booking requests appear here for review."
                            : "Try a different status."
                      }
                      action={
                        q ? (
                          <Button variant="outline" size="sm" onClick={() => search("")}>
                            Clear search
                          </Button>
                        ) : filter === "PENDING" ? null : (
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
                // Focusable and activatable, but still a row: giving a <tr> a
                // button role strips the table semantics a screen reader needs
                // to read the header for each cell.
                <TableRow
                  key={booking.id}
                  tabIndex={0}
                  aria-label={`Review booking for ${booking.customer?.full_name ?? "customer"}`}
                  className="cursor-pointer"
                  onClick={() => setReviewing(booking)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setReviewing(booking);
                    }
                  }}
                >
                  {/* Customer and vehicle together: one identity, not two columns
                      that have to be read across. */}
                  <TableCell>
                    <PrimaryCell
                      title={booking.customer?.full_name ?? "Unknown customer"}
                      subtitle={booking.vehicle.display_name}
                    />
                  </TableCell>
                  <TableCell>{booking.service.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    <span className="text-foreground">
                      {formatDayLabel(booking.requested_start, timeZone)}
                    </span>
                    <span className="px-1.5 text-border">·</span>
                    {formatTime(booking.requested_start, timeZone)}
                  </TableCell>
                  {/* Who is doing it - the question the pending queue exists to
                      answer, and the first thing to check on a confirmed one. */}
                  <TableCell className={booking.job ? undefined : "text-muted-foreground"}>
                    {booking.job ? booking.job.employee_name : "Unassigned"}
                  </TableCell>
                  <TableCell>
                    {booking.job ? (
                      <JobStatusBadge status={booking.job.status} />
                    ) : (
                      <BookingStatusBadge status={booking.status} />
                    )}
                  </TableCell>
                  <TableCell className="text-right font-medium">
                    {formatPrice(booking.service.base_price)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="bookings" />
          </PanelFooter>
        ) : null}
      </DataPanel>

      <BookingReviewSheet
        booking={active}
        timeZone={timeZone}
        onOpenChange={(open) => !open && setReviewing(null)}
      />
    </div>
  );
}
