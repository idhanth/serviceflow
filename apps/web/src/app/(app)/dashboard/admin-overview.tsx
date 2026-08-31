"use client";

import { ArrowRight, CalendarDays, ClipboardList } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { DataPanel } from "@/components/data/data-panel";
import { SectionHeader } from "@/components/data/page-header";
import { StatStrip } from "@/components/data/stat-strip";
import { JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDayLabel, formatPrice, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking, Job } from "@/lib/types";

/** The calendar day a timestamp falls on, in the shop's timezone. */
function dayKey(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

function ScheduleRow({ job, timeZone }: { job: Job; timeZone: string }) {
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="focus-ring flex items-center gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
    >
      <time className="w-16 shrink-0 text-[13px] font-medium tabular-nums">
        {formatTime(job.scheduled_start, timeZone)}
      </time>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{job.service.name}</span>
        <span className="block truncate text-[12px] text-muted-foreground">
          {job.customer.full_name} · {job.vehicle.display_name}
        </span>
      </span>
      <span className="hidden w-32 shrink-0 truncate text-[13px] text-muted-foreground sm:block">
        {job.employee.full_name}
      </span>
      <JobStatusBadge status={job.status} />
    </Link>
  );
}

/**
 * What an owner opens first.
 *
 * Three questions, in the order they are asked: what needs a decision from me,
 * what is happening today, and what is waiting. Every number is counted from
 * the API - nothing here is illustrative.
 */
export function AdminOverview({ timeZone }: { timeZone: string }) {
  const pendingParams = { page: 1, page_size: 6, status: "PENDING" as const };
  const pending = usePagedResource<Booking>(
    queryKeys.bookings.list(pendingParams),
    "bookings",
    pendingParams,
  );

  const upcomingParams = { page: 1, page_size: 50, status: "ASSIGNED" as const };
  const upcoming = usePagedResource<Job>(queryKeys.jobs.list(upcomingParams), "jobs", upcomingParams);

  const runningParams = { page: 1, page_size: 20, status: "IN_PROGRESS" as const };
  const running = usePagedResource<Job>(queryKeys.jobs.list(runningParams), "jobs", runningParams);

  // Today's work if there is any; otherwise the next day that has some. A shop
  // closed on a Sunday should be told what Monday looks like, not shown a void.
  const schedule = useMemo(() => {
    const jobs = [...(running.data?.data ?? []), ...(upcoming.data?.data ?? [])].sort((a, b) =>
      a.scheduled_start.localeCompare(b.scheduled_start),
    );
    if (jobs.length === 0) return { day: null, jobs: [] as Job[], isToday: true };

    const today = dayKey(new Date().toISOString(), timeZone);
    const todays = jobs.filter((job) => dayKey(job.scheduled_start, timeZone) === today);
    if (todays.length > 0) return { day: today, jobs: todays, isToday: true };

    const nextDay = dayKey(jobs[0].scheduled_start, timeZone);
    return {
      day: nextDay,
      jobs: jobs.filter((job) => dayKey(job.scheduled_start, timeZone) === nextDay),
      isToday: false,
    };
  }, [running.data, upcoming.data, timeZone]);

  const loading = pending.isPending || upcoming.isPending || running.isPending;

  return (
    <div className="space-y-6">
      <StatStrip
        stats={[
          {
            label: "Awaiting review",
            value: pending.data?.meta.total,
            href: "/bookings",
            emphasis: true,
          },
          { label: "In progress", value: running.data?.meta.total, href: "/jobs" },
          { label: "Scheduled ahead", value: upcoming.data?.meta.total, href: "/calendar" },
          {
            label: schedule.isToday ? "On today" : "Next working day",
            value: schedule.jobs.length,
            href: "/calendar",
          },
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <section className="space-y-3">
          <SectionHeader
            title={schedule.isToday ? "Today" : "Next working day"}
            description={
              schedule.day
                ? formatDayLabel(`${schedule.day}T12:00:00Z`, "UTC")
                : "Nothing scheduled yet"
            }
            action={
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/calendar" />}>
                Calendar
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            }
          />

          <DataPanel>
            {loading ? (
              <div className="divide-y">
                {[0, 1, 2].map((row) => (
                  <div key={row} className="flex items-center gap-4 px-4 py-3">
                    <Skeleton className="h-4 w-14" />
                    <Skeleton className="h-4 flex-1" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                ))}
              </div>
            ) : upcoming.isError ? (
              <ErrorState error={upcoming.error} onRetry={() => upcoming.refetch()} />
            ) : schedule.jobs.length === 0 ? (
              <EmptyState
                icon={CalendarDays}
                title="Nothing on the board"
                description="Confirm a booking and it will appear here with its technician and time."
                action={
                  <Button size="sm" render={<Link href="/bookings" />}>
                    Review bookings
                  </Button>
                }
              />
            ) : (
              <div className="divide-y">
                {schedule.jobs.map((job) => (
                  <ScheduleRow key={job.id} job={job} timeZone={timeZone} />
                ))}
              </div>
            )}
          </DataPanel>
        </section>

        <section className="space-y-3">
          <SectionHeader
            title="Awaiting review"
            description="Requests that need a technician and a yes"
            action={
              <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/bookings" />}>
                All
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            }
          />

          <DataPanel>
            {loading ? (
              <div className="divide-y">
                {[0, 1, 2].map((row) => (
                  <div key={row} className="space-y-2 px-4 py-3">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                ))}
              </div>
            ) : pending.isError ? (
              <ErrorState error={pending.error} onRetry={() => pending.refetch()} />
            ) : (pending.data?.data.length ?? 0) === 0 ? (
              <EmptyState
                icon={ClipboardList}
                title="Nothing waiting"
                description="New requests land here for review."
              />
            ) : (
              <div className="divide-y">
                {pending.data?.data.map((booking) => (
                  <Link
                    key={booking.id}
                    href="/bookings"
                    className="focus-ring flex items-start justify-between gap-3 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-medium">
                        {booking.customer?.full_name ?? "Unknown customer"}
                      </span>
                      <span className="block truncate text-[12px] text-muted-foreground">
                        {booking.service.name} ·{" "}
                        {formatDayLabel(booking.requested_start, timeZone)}
                      </span>
                    </span>
                    <span className="shrink-0 text-[13px] font-medium tabular-nums">
                      {formatPrice(booking.service.base_price)}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </DataPanel>
        </section>
      </div>
    </div>
  );
}
