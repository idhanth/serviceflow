"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CalendarDays, CheckCircle2, UserPlus, Users } from "lucide-react";
import Link from "next/link";

import { DataPanel } from "@/components/data/data-panel";
import { SectionHeader } from "@/components/data/page-header";
import { StatStrip } from "@/components/data/stat-strip";
import { JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetchData, ApiError } from "@/lib/api-client";
import { formatDayLabel, formatRelative, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { DashboardData, ScheduleEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

function EntryRow({
  entry,
  timeZone,
  showDay = false,
  note,
}: {
  entry: ScheduleEntry;
  timeZone: string;
  showDay?: boolean;
  note?: React.ReactNode;
}) {
  return (
    <Link
      href={`/jobs/${entry.id}`}
      className="focus-ring flex items-center gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
    >
      <span className="w-[74px] shrink-0">
        <time className="block text-[13px] font-medium tabular-nums">
          {formatTime(entry.scheduled_start, timeZone)}
        </time>
        {showDay ? (
          <span className="block text-[11px] text-muted-foreground">
            {formatDayLabel(entry.scheduled_start, timeZone)}
          </span>
        ) : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{entry.service_name}</span>
        <span className="block truncate text-[12px] text-muted-foreground">
          {entry.customer_name}
          {entry.customer_address ? ` · ${entry.customer_address}` : ""}
        </span>
      </span>
      <span
        className={cn(
          "hidden w-32 shrink-0 truncate text-[13px] sm:block",
          entry.employee_name ? "text-muted-foreground" : "font-medium text-status-pending",
        )}
      >
        {note ?? entry.employee_name ?? "Unassigned"}
      </span>
      <JobStatusBadge status={entry.status} />
    </Link>
  );
}

function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="divide-y">
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex items-center gap-4 px-4 py-3">
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  );
}

/**
 * The operations dashboard.
 *
 * Every element answers a question someone acts on: how busy today is, who is
 * out working, what is running late, what still has nobody assigned, and who
 * just became a customer. There are no charts, because nothing here is a trend.
 * All of it comes from one aggregate API call.
 */
export function OperationsDashboard({
  timeZone,
  canDispatch,
}: {
  timeZone: string;
  canDispatch: boolean;
}) {
  const query = useQuery<DashboardData, ApiError>({
    queryKey: queryKeys.dashboard.all,
    queryFn: () => apiFetchData<DashboardData>("dashboard"),
    refetchInterval: 60_000,
  });

  if (query.isError) {
    return (
      <DataPanel>
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      </DataPanel>
    );
  }

  const data = query.data;
  const counts = data?.counts;
  const attention = [...(data?.overdue ?? []), ...(data?.needs_attention ?? [])];

  return (
    <div className="space-y-6">
      <StatStrip
        className="sm:grid-cols-3 lg:grid-cols-6"
        stats={[
          { label: "Bookings today", value: counts?.bookings_today, href: "/schedule" },
          { label: "In progress", value: counts?.jobs_in_progress, href: "/jobs?status=IN_PROGRESS" },
          { label: "Completed today", value: counts?.jobs_completed_today, href: "/jobs?status=COMPLETED" },
          { label: "Still to do today", value: counts?.jobs_remaining_today, href: "/schedule" },
          {
            label: "Technicians working",
            value: counts ? `${counts.technicians_working_today} of ${counts.technicians_total}` : undefined,
            href: "/schedule",
          },
          {
            label: "Need a technician",
            value: counts?.unassigned_jobs,
            href: "/jobs?status=NEW",
            emphasis: true,
          },
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <section className="space-y-3">
          <SectionHeader
            title="Upcoming"
            description="The next scheduled visits, soonest first"
            action={
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/schedule" />}>
                Schedule
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            }
          />
          <DataPanel>
            {query.isPending ? (
              <ListSkeleton rows={5} />
            ) : (data?.upcoming.length ?? 0) === 0 ? (
              <EmptyState
                icon={CalendarDays}
                title="Nothing scheduled ahead"
                description="Assign a technician to a booking and the visit appears here."
                action={
                  canDispatch ? (
                    <Button size="sm" render={<Link href="/bookings/new" />}>
                      Create booking
                    </Button>
                  ) : null
                }
              />
            ) : (
              <div className="divide-y">
                {data?.upcoming.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} timeZone={timeZone} showDay />
                ))}
              </div>
            )}
          </DataPanel>
        </section>

        <div className="space-y-6">
          <section className="space-y-3">
            <SectionHeader
              title="Needs attention"
              description="Running late, or starting soon with nobody assigned"
            />
            <DataPanel>
              {query.isPending ? (
                <ListSkeleton />
              ) : attention.length === 0 ? (
                <EmptyState
                  icon={CheckCircle2}
                  title="Nothing at risk"
                  description="Every job starting in the next two days has a technician, and nothing is running late."
                />
              ) : (
                <div className="divide-y">
                  {data?.overdue.map((entry) => (
                    <EntryRow
                      key={entry.id}
                      entry={entry}
                      timeZone={timeZone}
                      note={
                        <span className="inline-flex items-center gap-1 font-medium text-status-danger">
                          <AlertTriangle className="size-3.5" aria-hidden />
                          Not started
                        </span>
                      }
                    />
                  ))}
                  {data?.needs_attention.map((entry) => (
                    <EntryRow
                      key={entry.id}
                      entry={entry}
                      timeZone={timeZone}
                      showDay
                      note={
                        <span className="inline-flex items-center gap-1 font-medium text-status-pending">
                          <UserPlus className="size-3.5" aria-hidden />
                          Assign
                        </span>
                      }
                    />
                  ))}
                </div>
              )}
            </DataPanel>
          </section>

          <section className="space-y-3">
            <SectionHeader
              title="New customers"
              action={
                <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/customers?sort=-created_at" />}>
                  All
                  <ArrowRight className="size-3.5" aria-hidden />
                </Button>
              }
            />
            <DataPanel>
              {query.isPending ? (
                <ListSkeleton rows={3} />
              ) : (data?.recent_customers.length ?? 0) === 0 ? (
                <EmptyState icon={Users} title="No customers yet" description="Customers you add appear here." />
              ) : (
                <div className="divide-y">
                  {data?.recent_customers.map((customer) => (
                    <Link
                      key={customer.id}
                      href={`/customers/${customer.id}`}
                      className="focus-ring flex items-center justify-between gap-3 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-[13px] font-medium">{customer.full_name}</span>
                        <span className="block truncate text-[12px] text-muted-foreground">
                          {customer.address ?? "No address on file"}
                        </span>
                      </span>
                      <span className="shrink-0 text-[12px] text-muted-foreground">
                        {formatRelative(customer.created_at)}
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </DataPanel>
          </section>
        </div>
      </div>
    </div>
  );
}
