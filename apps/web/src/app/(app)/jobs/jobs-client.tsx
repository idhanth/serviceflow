"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { JobStatusBadge } from "@/components/data/status-badge";
import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDuration, formatRelative, formatWindow } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Job, JobStatus } from "@/lib/types";

const FILTERS = [
  { label: "Active", value: "active" },
  { label: "Assigned", value: "ASSIGNED" },
  { label: "In progress", value: "IN_PROGRESS" },
  { label: "Completed", value: "COMPLETED" },
  { label: "All", value: "all" },
] as const;

type Filter = (typeof FILTERS)[number]["value"];

export function JobsClient({ timeZone, isAdmin }: { timeZone: string; isAdmin: boolean }) {
  const [filter, setFilter] = useState<Filter>("active");
  const [page, setPage] = useState(1);

  // "Active" has no single status, so it is fetched as ASSIGNED and filtered
  // client-side against the in-progress rows on the same page.
  const params = {
    page,
    page_size: 12,
    status: filter === "all" || filter === "active" ? undefined : (filter as JobStatus),
  };
  const query = usePagedResource<Job>(queryKeys.jobs.list(params), "jobs", params);

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  const all = query.data?.data ?? [];
  const jobs =
    filter === "active"
      ? all.filter((job) => job.status === "ASSIGNED" || job.status === "IN_PROGRESS")
      : all;
  const showEmpty = query.isSuccess && jobs.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title={isAdmin ? "Jobs" : "My jobs"}
        description={
          isAdmin
            ? "Every job across the shop, and where each one stands."
            : "The work assigned to you."
        }
      />

      <div
        role="group"
        aria-label="Filter jobs"
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

      {showEmpty ? (
        <Card>
          <EmptyState
            icon={Sparkles}
            title={filter === "active" ? "No active jobs" : "No jobs match this filter"}
            description={
              filter === "active"
                ? isAdmin
                  ? "Confirm a pending booking to create work for the team."
                  : "Nothing is assigned to you right now. Enjoy the quiet."
                : "Try a different status filter."
            }
            action={
              filter === "active" ? null : (
                <Button variant="outline" size="sm" onClick={() => changeFilter("active")}>
                  Show active jobs
                </Button>
              )
            }
          />
        </Card>
      ) : null}

      <ul className="space-y-4">
        {jobs.map((job) => (
          <li key={job.id}>
            <Card className="p-5 transition-colors duration-150 hover:bg-accent/30">
              <Link
                href={`/jobs/${job.id}`}
                className="flex flex-col gap-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-medium">{job.service.name}</h2>
                    <JobStatusBadge status={job.status} />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {formatWindow(job.scheduled_start, job.scheduled_end, timeZone)} ·{" "}
                    {formatRelative(job.scheduled_start)}
                  </p>
                  <p className="text-sm">
                    {job.customer.full_name} · {job.vehicle.display_name}
                  </p>
                  {isAdmin ? (
                    <p className="text-sm text-muted-foreground">
                      Technician: {job.employee.full_name}
                    </p>
                  ) : null}
                </div>
                <div className="shrink-0 text-sm text-muted-foreground">
                  {formatDuration(job.service.duration_minutes)}
                </div>
              </Link>
            </Card>
          </li>
        ))}
      </ul>

      {query.data && filter !== "active" ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="jobs" />
      ) : null}
    </div>
  );
}
