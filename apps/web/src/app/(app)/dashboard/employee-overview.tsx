"use client";

import { ArrowRight, CalendarDays } from "lucide-react";
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
import { formatDayLabel, formatDuration, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Job } from "@/lib/types";

function dayKey(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

/**
 * A technician's day.
 *
 * One question: what am I working on, and what is next. The job in progress is
 * pulled to the top because it is the only one they can act on right now.
 */
export function EmployeeOverview({ timeZone }: { timeZone: string }) {
  const assignedParams = { page: 1, page_size: 50, status: "ASSIGNED" as const };
  const assigned = usePagedResource<Job>(queryKeys.jobs.list(assignedParams), "jobs", assignedParams);

  const runningParams = { page: 1, page_size: 10, status: "IN_PROGRESS" as const };
  const running = usePagedResource<Job>(queryKeys.jobs.list(runningParams), "jobs", runningParams);

  const doneParams = { page: 1, page_size: 5, status: "COMPLETED" as const };
  const done = usePagedResource<Job>(queryKeys.jobs.list(doneParams), "jobs", doneParams);

  const schedule = useMemo(() => {
    const jobs = [...(running.data?.data ?? []), ...(assigned.data?.data ?? [])].sort((a, b) =>
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
  }, [assigned.data, running.data, timeZone]);

  const current = running.data?.data[0] ?? null;
  const loading = assigned.isPending || running.isPending;

  return (
    <div className="space-y-6">
      <StatStrip
        stats={[
          { label: schedule.isToday ? "On today" : "Next working day", value: schedule.jobs.length },
          { label: "In progress", value: running.data?.meta.total, emphasis: true },
          { label: "Assigned to me", value: assigned.data?.meta.total, href: "/jobs" },
          { label: "Completed", value: done.data?.meta.total },
        ]}
      />

      {current ? (
        <section className="space-y-3">
          <SectionHeader title="On the ramp" description="The job you have started" />
          <DataPanel className="border-accent-solid/30 bg-accent-solid/[0.04]">
            <div className="flex flex-wrap items-center justify-between gap-4 p-4">
              <div className="min-w-0">
                <p className="truncate text-[15px] font-medium">{current.service.name}</p>
                <p className="truncate text-[13px] text-muted-foreground">
                  {current.customer.full_name} · {current.vehicle.display_name}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <JobStatusBadge status={current.status} variant="chip" />
                <Button size="sm" render={<Link href={`/jobs/${current.id}`} />}>
                  Open job
                </Button>
              </div>
            </div>
          </DataPanel>
        </section>
      ) : null}

      <section className="space-y-3">
        <SectionHeader
          title={schedule.isToday ? "Today" : "Next working day"}
          description={
            schedule.day ? formatDayLabel(`${schedule.day}T12:00:00Z`, "UTC") : "Nothing booked yet"
          }
          action={
            <Button variant="ghost" size="sm" className="h-7 px-2 text-[13px]" render={<Link href="/jobs" />}>
              All work
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
                </div>
              ))}
            </div>
          ) : assigned.isError ? (
            <ErrorState error={assigned.error} onRetry={() => assigned.refetch()} />
          ) : schedule.jobs.length === 0 ? (
            <EmptyState
              icon={CalendarDays}
              title="Nothing assigned"
              description="When a booking is confirmed onto you, it appears here."
            />
          ) : (
            <div className="divide-y">
              {schedule.jobs.map((job) => (
                <Link
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className="focus-ring flex items-center gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                >
                  <time className="w-16 shrink-0 text-[13px] font-medium tabular-nums">
                    {formatTime(job.scheduled_start, timeZone)}
                  </time>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">
                      {job.service.name}
                    </span>
                    <span className="block truncate text-[12px] text-muted-foreground">
                      {job.customer.full_name} · {job.vehicle.display_name}
                    </span>
                  </span>
                  <span className="hidden shrink-0 text-[13px] text-muted-foreground sm:block">
                    {formatDuration(job.service.duration_minutes)}
                  </span>
                  <JobStatusBadge status={job.status} />
                </Link>
              ))}
            </div>
          )}
        </DataPanel>
      </section>

      {(done.data?.data.length ?? 0) > 0 ? (
        <section className="space-y-3">
          <SectionHeader title="Recently finished" description="Your last few jobs" />
          <DataPanel>
            <div className="divide-y">
              {done.data?.data.map((job) => (
                <Link
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className="focus-ring flex items-center justify-between gap-4 px-4 py-2.5 transition-colors duration-75 hover:bg-muted/40"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[13px]">{job.service.name}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">
                      {job.customer.full_name} · {job.vehicle.display_name}
                    </span>
                  </span>
                  <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
                    {formatDayLabel(job.scheduled_start, timeZone)}
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
