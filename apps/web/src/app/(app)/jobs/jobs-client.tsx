"use client";

import { Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { MobileList, MobileRow } from "@/components/data/mobile-list";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { Segmented } from "@/components/data/segmented";
import { JobStatusBadge } from "@/components/data/status-badge";
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
import { formatDayLabel, formatDuration, formatTime } from "@/lib/format";
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

/**
 * The work board.
 *
 * A table, not a stack of cards: a shop lead needs to compare a day's jobs at a
 * glance - who has what, when, and how far along - and cards make every row
 * cost the same vertical space as a paragraph.
 */
export function JobsClient({ timeZone, isAdmin }: { timeZone: string; isAdmin: boolean }) {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("active");
  const [page, setPage] = useState(1);

  // "Active" is two statuses, and the API filters by one. Fetching everything
  // and filtering the current page client-side looked like this: page one of a
  // date-ordered list is all completed work, so the board said "no active jobs"
  // while its own footer counted 198. Active is fetched as its two statuses and
  // merged; the rest go through the ordinary paged query.
  const isActive = filter === "active";
  const params = {
    page,
    page_size: 20,
    status: isActive || filter === "all" ? undefined : (filter as JobStatus),
  };
  const query = usePagedResource<Job>(queryKeys.jobs.list(params), "jobs", params, {
    enabled: !isActive,
  });

  const assignedParams = { page: 1, page_size: 100, status: "ASSIGNED" as JobStatus };
  const assigned = usePagedResource<Job>(queryKeys.jobs.list(assignedParams), "jobs", assignedParams, {
    enabled: isActive,
  });
  const runningParams = { page: 1, page_size: 100, status: "IN_PROGRESS" as JobStatus };
  const running = usePagedResource<Job>(queryKeys.jobs.list(runningParams), "jobs", runningParams, {
    enabled: isActive,
  });

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  const jobs = isActive
    ? [...(running.data?.data ?? []), ...(assigned.data?.data ?? [])].sort((a, b) =>
        a.scheduled_start.localeCompare(b.scheduled_start),
      )
    : (query.data?.data ?? []);

  const pending = isActive ? assigned.isPending || running.isPending : query.isPending;
  const failed = isActive ? assigned.isError || running.isError : query.isError;
  const error = isActive ? (assigned.error ?? running.error) : query.error;
  const refetch = isActive
    ? () => {
        void assigned.refetch();
        void running.refetch();
      }
    : () => void query.refetch();
  const showEmpty = !pending && !failed && jobs.length === 0;
  const columns = isAdmin ? 5 : 4;

  function open(jobId: string) {
    router.push(`/jobs/${jobId}`);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={isAdmin ? "Jobs" : "My work"}
        description={
          isAdmin
            ? "Every job across the shop, and where each one stands."
            : "The work assigned to you, newest first."
        }
      />

      <Toolbar>
        <Segmented label="Filter jobs" value={filter} onChange={changeFilter} options={FILTERS} />
      </Toolbar>

      <DataPanel>
        <MobileList>
          {jobs.map((job) => (
            <MobileRow
              key={job.id}
              onClick={() => open(job.id)}
              title={job.service.name}
              subtitle={`${job.customer.full_name} · ${job.vehicle.display_name}`}
              trailing={
                <span className="text-[12px] text-muted-foreground">
                  {formatDuration(job.service.duration_minutes)}
                </span>
              }
              meta={
                <>
                  <span className="text-[12px] text-muted-foreground">
                    {formatDayLabel(job.scheduled_start, timeZone)} ·{" "}
                    {formatTime(job.scheduled_start, timeZone)}
                  </span>
                  <JobStatusBadge status={job.status} />
                </>
              }
            />
          ))}
        </MobileList>

        <div className="hidden overflow-x-auto md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[230px]">Job</TableHead>
                <TableHead className="min-w-[200px]">Scheduled</TableHead>
                {isAdmin ? <TableHead className="min-w-[140px]">Technician</TableHead> : null}
                <TableHead className="min-w-[140px]">Status</TableHead>
                <TableHead className="min-w-[90px] text-right">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pending ? <TableSkeletonRows columns={columns} /> : null}

              {failed ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <ErrorState error={error} onRetry={refetch} />
                  </TableCell>
                </TableRow>
              ) : null}

              {showEmpty ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <EmptyState
                      icon={Wrench}
                      title={filter === "active" ? "No active jobs" : "No jobs match this filter"}
                      description={
                        filter === "active"
                          ? isAdmin
                            ? "Confirm a pending booking to create work for the team."
                            : "Nothing is assigned to you right now."
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
                  </TableCell>
                </TableRow>
              ) : null}

              {jobs.map((job) => (
                <TableRow
                  key={job.id}
                  tabIndex={0}
                  aria-label={`Open ${job.service.name} for ${job.customer.full_name}`}
                  className="cursor-pointer"
                  onClick={() => open(job.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      open(job.id);
                    }
                  }}
                >
                  <TableCell>
                    {/* A real link in the primary cell: the row click is a
                        convenience, but opening a job in a new tab should work
                        the way it does everywhere else. */}
                    <PrimaryCell
                      title={
                        <Link
                          href={`/jobs/${job.id}`}
                          className="focus-ring hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {job.service.name}
                        </Link>
                      }
                      subtitle={`${job.customer.full_name} · ${job.vehicle.display_name}`}
                    />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <span className="text-foreground">
                      {formatDayLabel(job.scheduled_start, timeZone)}
                    </span>
                    <span className="px-1.5 text-border">·</span>
                    {formatTime(job.scheduled_start, timeZone)}
                  </TableCell>
                  {isAdmin ? <TableCell>{job.employee.full_name}</TableCell> : null}
                  <TableCell>
                    <JobStatusBadge status={job.status} />
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatDuration(job.service.duration_minutes)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {/* The active view is a merged list, so it reports its own size rather
            than a page position that would not mean anything. */}
        {isActive ? (
          jobs.length > 0 ? (
            <PanelFooter>
              <p className="text-[12px] text-muted-foreground">
                <span className="tabular-nums text-foreground">{jobs.length}</span> active{" "}
                {jobs.length === 1 ? "job" : "jobs"}
              </p>
            </PanelFooter>
          ) : null
        ) : query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="jobs" />
          </PanelFooter>
        ) : null}
      </DataPanel>
    </div>
  );
}
