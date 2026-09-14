"use client";

import { History } from "lucide-react";
import { useState } from "react";

import { DataPanel, PanelFooter } from "@/components/data/data-panel";
import { FieldSelect } from "@/components/data/field-select";
import { PageHeader } from "@/components/data/page-header";
import { Segmented } from "@/components/data/segmented";
import { PaginationControls } from "@/components/data/pagination-controls";
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
import { useQuery } from "@tanstack/react-query";

import { usePagedResource } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDate, formatDayLabel, formatRelative, formatTime, initialsOf } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { AuditActor, AuditEntry } from "@/lib/types";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const COLUMNS = 3;

/** Broad groups, so an admin can ask "what happened to bookings" in one click. */
const AREAS = [
  { label: "Everything", value: "all", resourceType: undefined },
  { label: "Bookings", value: "booking", resourceType: "booking" },
  { label: "Jobs", value: "job", resourceType: "job" },
  { label: "Customers", value: "customer", resourceType: "customer" },
  { label: "Team", value: "employee", resourceType: "employee" },
  { label: "Access", value: "member", resourceType: "member" },
  { label: "Catalog", value: "service", resourceType: "service" },
] as const;

const PERIODS = [
  { label: "24 hours", value: "1", days: 1 },
  { label: "7 days", value: "7", days: 7 },
  { label: "30 days", value: "30", days: 30 },
  { label: "All time", value: "all", days: null },
] as const;

type Area = (typeof AREAS)[number]["value"];
type Period = (typeof PERIODS)[number]["value"];

/**
 * An audit entry as a sentence.
 *
 * The stored metadata is a small key/value bag, which is the right shape for a
 * table nobody can edit and the wrong shape for a person to read. "Job -
 * employee: Marcus Webb · scheduled start: 2026-09-02T19:00:00-04:00" is a log
 * line; "Assigned Marcus Webb, Wed, Sep 2 at 4:00 PM" is what happened.
 */
const ACTION_VERBS: Record<string, string> = {
  BOOKING_CREATED: "Requested a booking",
  BOOKING_CONFIRMED: "Confirmed a booking",
  BOOKING_REJECTED: "Declined a booking",
  BOOKING_RESCHEDULED: "Moved a booking",
  BOOKING_CANCELLED: "Cancelled a booking",
  JOB_ASSIGNED: "Assigned a job",
  JOB_REASSIGNED: "Reassigned a job",
  JOB_STARTED: "Started a job",
  JOB_COMPLETED: "Completed a job",
  JOB_CANCELLED: "Cancelled a job",
  NOTE_ADDED: "Added a note",
  NOTE_DELETED: "Removed a note",
  PHOTO_DELETED: "Removed a photo",
  CUSTOMER_CREATED: "Added a customer",
  CUSTOMER_UPDATED: "Updated a customer",
  CUSTOMER_ARCHIVED: "Archived a customer",
  EMPLOYEE_CREATED: "Added a team member",
  EMPLOYEE_UPDATED: "Updated a team member",
  EMPLOYEE_DEACTIVATED: "Deactivated a team member",
  EMPLOYEE_REACTIVATED: "Reactivated a team member",
  SERVICE_CREATED: "Added a service",
  SERVICE_UPDATED: "Updated a service",
  SERVICE_RETIRED: "Retired a service",
  USER_INVITED: "Added a member",
  USER_ROLE_CHANGED: "Changed a member's role",
  MEMBER_SUSPENDED: "Suspended a member",
  MEMBER_REACTIVATED: "Reactivated a member",
  ORGANIZATION_UPDATED: "Updated business settings",
  TENANT_CREATED: "Created the business",
  AVAILABILITY_UPDATED: "Updated working hours",
  AVAILABILITY_OVERRIDE_SET: "Set a day override",
  AVAILABILITY_OVERRIDE_REMOVED: "Removed a day override",
};

function describeAction(action: string): string {
  if (ACTION_VERBS[action]) return ACTION_VERBS[action];
  const words = action.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Destructive actions read differently; everything else is neutral. */
function isReversal(action: string): boolean {
  return /CANCELLED|REJECTED|DELETED|ARCHIVED|DEACTIVATED|RETIRED|SUSPENDED/.test(action);
}

/**
 * Which metadata keys deserve a word in front of them.
 *
 * Most do not: "Requested a booking · HVAC Inspection · Sarah Mitchell · Mon, Sep 7
 * at 4:30 PM" needs no labels to be understood, and adding them ("service:",
 * "requested start:") turns a sentence back into a log line.
 */
const METADATA_LABELS: Record<string, string> = {
  from: "from",
  to: "to",
  fields: "changed",
};

/** Renders one metadata value: dates become readable, flags become words. */
function renderValue(key: string, value: unknown, timeZone: string): string | null {
  if (value === null || value === "" || value === undefined) return null;
  if (key === "by_customer") return value === true ? "by the customer" : null;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return `${formatDayLabel(value, timeZone)} at ${formatTime(value, timeZone)}`;
  }
  return String(value);
}

function summarize(entry: AuditEntry, timeZone: string): string | null {
  if (!entry.metadata) return null;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(entry.metadata)) {
    const rendered = renderValue(key, value, timeZone);
    if (rendered === null) continue;
    const label = METADATA_LABELS[key] ?? "";
    parts.push(label ? `${label} ${rendered}` : rendered);
  }
  return parts.length ? parts.join(" · ") : null;
}

/** The oldest timestamp a period includes, or undefined for all time. */
function boundaryFor(period: Period): string | undefined {
  const days = PERIODS.find((option) => option.value === period)?.days ?? null;
  return days ? new Date(Date.now() - days * 86_400_000).toISOString() : undefined;
}

export function ActivityClient({ timeZone }: { timeZone: string }) {
  const [area, setArea] = useState<Area>("all");
  const [period, setPeriod] = useState<Period>("7");
  // Held in state, not derived during render: a boundary recomputed every render
  // would change the query key every render, and the feed would never settle.
  const [since, setSince] = useState<string | undefined>(() => boundaryFor("7"));
  const [actorId, setActorId] = useState("all");
  const [page, setPage] = useState(1);

  const params = {
    page,
    page_size: 20,
    resource_type: AREAS.find((option) => option.value === area)?.resourceType,
    actor_user_id: actorId === "all" ? undefined : actorId,
    since,
  };

  const query = usePagedResource<AuditEntry>(queryKeys.activity.list(params), "activity", params);
  const actors = useQuery<AuditActor[]>({
    queryKey: queryKeys.activity.actors,
    queryFn: () => apiFetchData<AuditActor[]>("activity/actors"),
  });

  function reset<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPage(1);
    };
  }

  const entries = query.data?.data ?? [];
  const showEmpty = query.isSuccess && entries.length === 0;
  const filtered = area !== "all" || period !== "7" || actorId !== "all";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="Who changed what, and when. Entries are permanent and cannot be edited."
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <Segmented
          label="Filter by area"
          value={area}
          onChange={reset(setArea)}
          options={AREAS.map((option) => ({ label: option.label, value: option.value }))}
        />

        <div className="flex flex-wrap items-center gap-2">
          <FieldSelect
            label="Filter by person"
            value={actorId}
            onChange={reset(setActorId)}
            className="w-44"
          >
            <option value="all">Anyone</option>
            {(actors.data ?? []).map((actor) => (
              <option key={actor.id} value={actor.id}>
                {actor.full_name}
              </option>
            ))}
          </FieldSelect>

          <Segmented
            label="Filter by period"
            value={period}
            onChange={(next) => {
              setPeriod(next);
              setSince(boundaryFor(next));
              setPage(1);
            }}
            options={PERIODS.map((option) => ({ label: option.label, value: option.value }))}
          />
        </div>
      </div>

      <DataPanel>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[180px]">Who</TableHead>
                <TableHead>What happened</TableHead>
                <TableHead className="w-[120px] text-right">When</TableHead>
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
                      icon={History}
                      title={filtered ? "Nothing in this range" : "No activity yet"}
                      description={
                        filtered
                          ? "Try a wider period, or a different area."
                          : "Once your team starts confirming and working on bookings, the trail appears here."
                      }
                      action={
                        filtered ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setArea("all");
                              setPeriod("all");
                              setSince(undefined);
                              setActorId("all");
                              setPage(1);
                            }}
                          >
                            Clear filters
                          </Button>
                        ) : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {entries.map((entry) => {
                const detail = summarize(entry, timeZone);
                return (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap align-top">
                      <div className="flex items-center gap-2.5 py-0.5">
                        <Avatar className="size-6">
                          <AvatarFallback className="text-[10px]">
                            {initialsOf(entry.actor_name)}
                          </AvatarFallback>
                        </Avatar>
                        <span className="truncate font-medium">{entry.actor_name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="w-full whitespace-normal align-top">
                      <div className="py-0.5">
                        <span
                          className={
                            isReversal(entry.action) ? "text-status-danger" : "text-foreground"
                          }
                        >
                          {describeAction(entry.action)}
                        </span>
                        {detail ? (
                          <span className="text-muted-foreground"> · {detail}</span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right align-top text-muted-foreground">
                      <time dateTime={entry.created_at} title={formatDate(entry.created_at)}>
                        {formatRelative(entry.created_at)}
                      </time>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="entries" />
          </PanelFooter>
        ) : null}
      </DataPanel>
    </div>
  );
}
