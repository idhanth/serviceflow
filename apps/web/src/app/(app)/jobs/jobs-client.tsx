"use client";

import { Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { MobileList, MobileRow } from "@/components/data/mobile-list";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { Segmented } from "@/components/data/segmented";
import { JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDayLabel, formatDuration, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Job, JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const TEAM_FILTERS = [
  { label: "Needs technician", value: "NEW" },
  { label: "Scheduled", value: "SCHEDULED" },
  { label: "In progress", value: "IN_PROGRESS" },
  { label: "Completed", value: "COMPLETED" },
  { label: "All", value: "all" },
] as const;

const MY_FILTERS = [
  { label: "Upcoming", value: "SCHEDULED" },
  { label: "In progress", value: "IN_PROGRESS" },
  { label: "Completed", value: "COMPLETED" },
  { label: "All", value: "all" },
] as const;

type Filter = "NEW" | "SCHEDULED" | "IN_PROGRESS" | "COMPLETED" | "all";

/**
 * The work board.
 *
 * A table, not a stack of cards: a dispatcher compares a day's jobs at a glance -
 * who has what, when, and how far along - and cards would make every row cost a
 * paragraph of vertical space. Pagination and search happen on the server.
 */
export function JobsClient({
  timeZone,
  team,
  initialFilter,
}: {
  timeZone: string;
  team: boolean;
  initialFilter?: string;
}) {
  const router = useRouter();
  const options = team ? TEAM_FILTERS : MY_FILTERS;
  const fallback: Filter = team ? "NEW" : "SCHEDULED";
  const [filter, setFilter] = useState<Filter>(
    options.some((option) => option.value === initialFilter) ? (initialFilter as Filter) : fallback,
  );
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  // Work that is still ahead reads soonest-first; finished work newest-first.
  const upcoming = filter === "NEW" || filter === "SCHEDULED";
  const params = {
    page,
    page_size: 20,
    q,
    status: filter === "all" ? undefined : (filter as JobStatus),
    timeframe: upcoming ? "upcoming" : undefined,
  };
  const query = usePagedResource<Job>(queryKeys.jobs.list(params), "jobs", params);

  const needsParams = { page: 1, page_size: 1, status: "NEW" as JobStatus, timeframe: "upcoming" };
  const needs = usePagedResource<Job>(queryKeys.jobs.list(needsParams), "jobs", needsParams, {
    enabled: team,
  });

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  const jobs = query.data?.data ?? [];
  const columns = team ? 5 : 4;
  const open = (jobId: string) => router.push(`/jobs/${jobId}`);

  return (
    <div className="space-y-5">
      <PageHeader
        title={team ? "Jobs" : "My Jobs"}
        description={
          team
            ? "Every job across the business, and where each one stands."
            : "The work assigned to you. Start a job when you arrive and complete it when you're done."
        }
      />

      <Toolbar className="justify-between">
        <Segmented
          label="Filter jobs"
          value={filter}
          onChange={changeFilter}
          options={options.map((option) =>
            option.value === "NEW" ? { ...option, count: needs.data?.meta.total } : option,
          )}
        />
        <SearchInput
          value={q}
          onChange={(next) => {
            setQ(next);
            setPage(1);
          }}
          label="Search jobs"
          placeholder="Customer, address or service"
        />
      </Toolbar>

      <DataPanel>
        <MobileList>
          {jobs.map((job) => (
            <MobileRow
              key={job.id}
              onClick={() => open(job.id)}
              title={job.service.name}
              subtitle={`${job.customer.full_name}${job.customer.address ? ` · ${job.customer.address}` : ""}`}
              trailing={
                <span className="text-[12px] text-muted-foreground">
                  {formatDuration(job.service.duration_minutes)}
                </span>
              }
              meta={
                <>
                  <span className="text-[12px] text-muted-foreground">
                    {formatDayLabel(job.scheduled_start, timeZone)} · {formatTime(job.scheduled_start, timeZone)}
                    {team ? ` · ${job.employee?.full_name ?? "Unassigned"}` : ""}
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
                <TableHead className="min-w-[260px]">Job</TableHead>
                <TableHead className="min-w-[180px]">Scheduled</TableHead>
                {team ? <TableHead className="min-w-[150px]">Technician</TableHead> : null}
                <TableHead className="min-w-[140px]">Status</TableHead>
                <TableHead className="min-w-[90px] text-right">Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={columns} /> : null}

              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}

              {query.isSuccess && jobs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <EmptyState
                      icon={Wrench}
                      title={
                        q
                          ? `No jobs match “${q}”`
                          : filter === "NEW"
                            ? "Every upcoming job has a technician"
                            : team
                              ? "No jobs with this status"
                              : "Nothing here right now"
                      }
                      description={
                        q
                          ? "Try a customer name, street or service."
                          : filter === "NEW"
                            ? "New bookings without a technician land here until someone is assigned."
                            : "Try a different status."
                      }
                      action={
                        q ? (
                          <Button variant="outline" size="sm" onClick={() => setQ("")}>
                            Clear search
                          </Button>
                        ) : null
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
                      subtitle={`${job.customer.full_name}${job.customer.address ? ` · ${job.customer.address}` : ""}`}
                    />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <span className="text-foreground">{formatDayLabel(job.scheduled_start, timeZone)}</span>
                    <span className="px-1.5 text-border">·</span>
                    {formatTime(job.scheduled_start, timeZone)}
                  </TableCell>
                  {team ? (
                    <TableCell className={cn(!job.employee && "font-medium text-status-pending")}>
                      {job.employee?.full_name ?? "Unassigned"}
                    </TableCell>
                  ) : null}
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
        {query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="jobs" />
          </PanelFooter>
        ) : null}
      </DataPanel>
    </div>
  );
}
