"use client";

import { useQuery } from "@tanstack/react-query";
import { Archive, ArrowLeft, CalendarPlus, ClipboardList, Mail, MapPin, Pencil, Phone } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { DataPanel, PanelFooter } from "@/components/data/data-panel";
import { SectionHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { Segmented } from "@/components/data/segmented";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData, ApiError } from "@/lib/api-client";
import { formatDate, formatDayLabel, formatPrice, formatRelative, formatTime } from "@/lib/format";
import { OPERATIONS_KEYS, queryKeys } from "@/lib/query-keys";
import type { Booking, Customer } from "@/lib/types";

import { CustomerFormDialog } from "../customer-form-dialog";

const TABS = [
  { label: "Upcoming", value: "upcoming" },
  { label: "History", value: "past" },
] as const;

type Tab = (typeof TABS)[number]["value"];

/** One customer: how to reach them, where the work is, and every booking and job they've had. */
export function CustomerDetailClient({
  customerId,
  timeZone,
  canWrite,
  canArchive,
  canBook,
  canOpenJobs,
}: {
  customerId: string;
  timeZone: string;
  canWrite: boolean;
  canArchive: boolean;
  canBook: boolean;
  canOpenJobs: boolean;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("upcoming");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const customer = useQuery<Customer, ApiError>({
    queryKey: queryKeys.customers.detail(customerId),
    queryFn: () => apiFetchData<Customer>(`customers/${customerId}`),
  });
  const params = { customer_id: customerId, timeframe: tab, page, page_size: 10 };
  const bookings = usePagedResource<Booking>(queryKeys.bookings.list(params), "bookings", params);

  const archive = useResourceMutation<void, Customer>(
    () => apiFetchData<Customer>(`customers/${customerId}`, { method: "DELETE" }),
    { invalidate: OPERATIONS_KEYS, successMessage: (result) => `${result.user.full_name} archived` },
  );

  if (customer.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-56" />
        <Card className="space-y-3 p-5">
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-4 w-1/2" />
        </Card>
      </div>
    );
  }
  if (customer.isError || !customer.data) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/customers" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Customers
        </Button>
        <Card>
          <ErrorState error={customer.error} onRetry={() => customer.refetch()} />
        </Card>
      </div>
    );
  }

  const person = customer.data;
  const rows = bookings.data?.data ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/customers" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Customers
        </Button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">{person.user.full_name}</h1>
              {person.archived ? (
                <span className="rounded border px-1.5 py-0.5 text-[12px] text-muted-foreground">Archived</span>
              ) : null}
            </div>
            <p className="text-[13px] text-muted-foreground">Customer since {formatDate(person.created_at)}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canBook && !person.archived ? (
              <Button size="sm" render={<Link href={`/bookings/new?customer_id=${person.id}`} />}>
                <CalendarPlus className="size-3.5" aria-hidden />
                New booking
              </Button>
            ) : null}
            {canWrite ? (
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="size-3.5" aria-hidden />
                Edit
              </Button>
            ) : null}
            {canArchive && !person.archived ? (
              <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setArchiving(true)}>
                <Archive className="size-3.5" aria-hidden />
                Archive
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Card className="space-y-4 p-5">
          <section className="space-y-2">
            <h2 className="text-[12px] text-muted-foreground">Contact</h2>
            <a href={`mailto:${person.user.email}`} className="focus-ring flex items-center gap-2 text-[13px] hover:underline">
              <Mail className="size-3.5 text-muted-foreground" aria-hidden />
              <span className="truncate">{person.user.email}</span>
            </a>
            {person.user.phone ? (
              <a href={`tel:${person.user.phone}`} className="focus-ring flex items-center gap-2 text-[13px] hover:underline">
                <Phone className="size-3.5 text-muted-foreground" aria-hidden />
                {person.user.phone}
              </a>
            ) : null}
            <p className="flex items-start gap-2 text-[13px]">
              <MapPin className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              {person.address ?? <span className="text-muted-foreground">No service address</span>}
            </p>
          </section>
          {person.notes ? (
            <section className="space-y-1.5 border-t pt-4">
              <h2 className="text-[12px] text-muted-foreground">Internal notes</h2>
              <p className="whitespace-pre-wrap text-[13px]">{person.notes}</p>
            </section>
          ) : null}
        </Card>

        <dl className="grid grid-cols-3 divide-x overflow-hidden rounded-lg border bg-surface lg:col-span-2">
          {[
            { label: "Bookings", value: person.booking_count },
            { label: "Jobs completed", value: person.completed_jobs },
            { label: "Last service", value: person.last_service_at ? formatRelative(person.last_service_at) : "—" },
          ].map((stat) => (
            <div key={stat.label} className="px-4 py-3">
              <dt className="text-[12px] text-muted-foreground">{stat.label}</dt>
              <dd className="mt-1 text-[20px] font-semibold tabular-nums">{stat.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <section className="space-y-3">
        <SectionHeader
          title="Bookings and jobs"
          action={
            <Segmented
              label="Show bookings"
              value={tab}
              onChange={(next) => {
                setTab(next);
                setPage(1);
              }}
              options={TABS}
            />
          }
        />
        <DataPanel>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[200px]">Service</TableHead>
                  <TableHead className="min-w-[170px]">When</TableHead>
                  <TableHead className="min-w-[140px]">Technician</TableHead>
                  <TableHead className="min-w-[140px]">Status</TableHead>
                  <TableHead className="min-w-[80px] text-right">Price</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bookings.isPending ? <TableSkeletonRows columns={5} rows={3} /> : null}
                {bookings.isError ? (
                  <TableRow>
                    <TableCell colSpan={5} className="p-0">
                      <ErrorState error={bookings.error} onRetry={() => bookings.refetch()} />
                    </TableCell>
                  </TableRow>
                ) : null}
                {bookings.isSuccess && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="p-0">
                      <EmptyState
                        icon={ClipboardList}
                        title={tab === "upcoming" ? "No upcoming bookings" : "No service history yet"}
                        description={tab === "upcoming" ? "Book them in and it will appear here." : "Completed and cancelled work appears here."}
                      />
                    </TableCell>
                  </TableRow>
                ) : null}
                {rows.map((booking) => (
                  <TableRow key={booking.id}>
                    <TableCell className="font-medium">
                      <Link href={`/bookings/${booking.id}`} className="focus-ring hover:underline">
                        {booking.service.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      <span className="text-foreground">{formatDayLabel(booking.requested_start, timeZone)}</span>
                      <span className="px-1.5 text-border">·</span>
                      {formatTime(booking.requested_start, timeZone)}
                    </TableCell>
                    <TableCell className={booking.job?.employee_name ? undefined : "text-muted-foreground"}>
                      {booking.job?.employee_name ?? "Unassigned"}
                    </TableCell>
                    <TableCell>
                      {booking.job && canOpenJobs && booking.job.status !== "NEW" && booking.job.status !== "CANCELLED" ? (
                        <Link href={`/jobs/${booking.job.id}`} className="focus-ring">
                          <JobStatusBadge status={booking.job.status} />
                        </Link>
                      ) : (
                        <BookingStatusBadge status={booking.status} />
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatPrice(booking.service.base_price)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {bookings.data && bookings.data.meta.total > 0 ? (
            <PanelFooter>
              <PaginationControls meta={bookings.data.meta} onPageChange={setPage} noun="bookings" />
            </PanelFooter>
          ) : null}
        </DataPanel>
      </section>

      {canWrite ? (
        <CustomerFormDialog
          open={editing}
          onOpenChange={(open) => {
            setEditing(open);
            if (!open) void customer.refetch();
          }}
          customer={person}
        />
      ) : null}
      <ConfirmDialog
        open={archiving}
        onOpenChange={setArchiving}
        title={`Archive ${person.user.full_name}?`}
        description="They disappear from the customer list and can't be booked, but their history stays. Customers with upcoming bookings can't be archived until those are cancelled."
        confirmLabel="Archive customer"
        pendingLabel="Archiving..."
        onConfirm={async () => {
          await archive.mutateAsync();
          router.push("/customers");
        }}
      />
    </div>
  );
}
