"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, CalendarPlus, ChevronLeft, ChevronRight, UserRound } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { FieldSelect } from "@/components/data/field-select";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { Segmented } from "@/components/data/segmented";
import { JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api-client";
import {
  addDays,
  clockToMinutes,
  formatLocalDate,
  localDateOf,
  minutesIntoDay,
  minutesToLabel,
  startOfWeek,
  todayIn,
} from "@/lib/dates";
import { formatDuration, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { JobStatus, ScheduleEntry, ScheduleFeed, ScheduleLane } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "day" | "week";

const DAY_START = 6 * 60;
const DAY_END = 21 * 60;
const SPAN = DAY_END - DAY_START;
const HOURS = Array.from({ length: (DAY_END - DAY_START) / 60 }, (_, index) => DAY_START + index * 60);

/**
 * Jobs wear the product's status colours on a left rule rather than a filled
 * block: a day of solid colour reads as a chart, not a schedule. The written
 * status is always available alongside, so colour is never the only signal.
 */
const TONE: Record<JobStatus, string> = {
  NEW: "border-l-status-pending bg-status-pending/[0.09] hover:bg-status-pending/[0.16]",
  SCHEDULED: "border-l-status-info bg-status-info/[0.08] hover:bg-status-info/[0.14]",
  IN_PROGRESS: "border-l-status-active bg-status-active/[0.11] hover:bg-status-active/[0.18]",
  COMPLETED: "border-l-status-done bg-status-done/[0.08] hover:bg-status-done/[0.14]",
  CANCELLED: "border-l-border bg-muted/60 opacity-70 hover:opacity-90",
};

const STATUS_OPTIONS: { value: JobStatus; label: string }[] = [
  { value: "NEW", label: "New" },
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "IN_PROGRESS", label: "In progress" },
  { value: "COMPLETED", label: "Completed" },
  { value: "CANCELLED", label: "Cancelled" },
];

function percent(minutes: number): number {
  return ((Math.min(Math.max(minutes, DAY_START), DAY_END) - DAY_START) / SPAN) * 100;
}

function entryLabel(entry: ScheduleEntry, timeZone: string): string {
  return `${entry.service_name} for ${entry.customer_name}, ${formatTime(entry.scheduled_start, timeZone)} to ${formatTime(
    entry.scheduled_end,
    timeZone,
  )}, ${entry.status.replace("_", " ").toLowerCase()}`;
}

/** One technician's day as a horizontal band: hours shaded where they work, jobs on top. */
function DayLane({
  lane,
  entries,
  date,
  timeZone,
}: {
  lane: ScheduleLane | null;
  entries: ScheduleEntry[];
  date: string;
  timeZone: string;
}) {
  const day = lane?.days.find((candidate) => candidate.date === date);
  const nowMinutes = localDateOf(new Date().toISOString(), timeZone) === date
    ? minutesIntoDay(new Date().toISOString(), timeZone)
    : null;

  return (
    <div className="grid grid-cols-[200px_minmax(0,1fr)] border-b last:border-b-0">
      <div className="flex min-w-0 flex-col justify-center border-r px-3 py-2">
        {lane ? (
          <>
            <p className="truncate text-[13px] font-medium">{lane.full_name}</p>
            <p className="truncate text-[12px] text-muted-foreground">
              {day && day.windows.length > 0
                ? day.windows.map((w) => `${minutesToLabel(clockToMinutes(w.start))}–${minutesToLabel(clockToMinutes(w.end))}`).join(", ")
                : (day?.unavailable_reason ?? "Not scheduled")}
            </p>
          </>
        ) : (
          <>
            <p className="truncate text-[13px] font-medium text-status-pending">Unassigned</p>
            <p className="truncate text-[12px] text-muted-foreground">Needs a technician</p>
          </>
        )}
      </div>
      <div className="relative h-[60px]">
        {/* Off hours are hatched; working hours are plain. The background is the
            availability, so a job placed outside it stands out at a glance. */}
        {lane ? (
          <div aria-hidden className="absolute inset-0 bg-[repeating-linear-gradient(135deg,transparent,transparent_5px,var(--muted)_5px,var(--muted)_6px)] opacity-70" />
        ) : null}
        {day?.windows.map((window) => {
          const left = percent(clockToMinutes(window.start));
          const right = percent(clockToMinutes(window.end));
          return (
            <div
              key={`${window.start}-${window.end}`}
              aria-hidden
              className="absolute inset-y-0 bg-surface"
              style={{ left: `${left}%`, width: `${right - left}%` }}
            />
          );
        })}
        {HOURS.map((hour) => (
          <div
            key={hour}
            aria-hidden
            className="absolute inset-y-0 border-l border-border/60"
            style={{ left: `${percent(hour)}%` }}
          />
        ))}
        {nowMinutes !== null && nowMinutes > DAY_START && nowMinutes < DAY_END ? (
          <div
            aria-hidden
            className="absolute inset-y-0 z-10 w-px bg-status-danger"
            style={{ left: `${percent(nowMinutes)}%` }}
          />
        ) : null}
        {entries.map((entry) => {
          const startsToday = localDateOf(entry.scheduled_start, timeZone) === date;
          const endsToday = localDateOf(entry.scheduled_end, timeZone) === date;
          const from = startsToday ? minutesIntoDay(entry.scheduled_start, timeZone) : 0;
          const to = endsToday ? minutesIntoDay(entry.scheduled_end, timeZone) : 24 * 60;
          const left = percent(from);
          const width = Math.max(percent(to) - left, 2.5);
          return (
            <Link
              key={entry.id}
              href={`/jobs/${entry.id}`}
              aria-label={entryLabel(entry, timeZone)}
              title={entryLabel(entry, timeZone)}
              className={cn(
                "focus-ring absolute inset-y-1.5 z-20 overflow-hidden rounded-sm border-l-[3px] px-1.5 py-1",
                "transition-colors duration-75",
                TONE[entry.status],
              )}
              style={{ left: `calc(${left}% + 1px)`, width: `calc(${width}% - 2px)` }}
            >
              <p className="truncate text-[12px] font-medium leading-tight">{entry.service_name}</p>
              <p className="truncate text-[11px] leading-tight text-muted-foreground">
                {formatTime(entry.scheduled_start, timeZone)} · {entry.customer_name}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function WeekCell({
  entries,
  hours,
  timeZone,
}: {
  entries: ScheduleEntry[];
  hours: string | null;
  timeZone: string;
}) {
  const shown = entries.slice(0, 4);
  return (
    <td className={cn("h-[92px] border-l p-1.5 align-top", hours === null && "bg-muted/35")}>
      <p className="mb-1 truncate text-[11px] text-muted-foreground">{hours ?? "Off"}</p>
      <ul className="space-y-1">
        {shown.map((entry) => (
          <li key={entry.id}>
            <Link
              href={`/jobs/${entry.id}`}
              aria-label={entryLabel(entry, timeZone)}
              title={entryLabel(entry, timeZone)}
              className={cn(
                "focus-ring block truncate rounded-sm border-l-[3px] px-1.5 py-0.5 text-[11px] transition-colors duration-75",
                TONE[entry.status],
              )}
            >
              <span className="tabular-nums text-muted-foreground">{formatTime(entry.scheduled_start, timeZone)}</span>{" "}
              <span className="font-medium">{entry.service_name}</span>
            </Link>
          </li>
        ))}
      </ul>
      {entries.length > shown.length ? (
        <p className="mt-1 text-[11px] text-muted-foreground">+{entries.length - shown.length} more</p>
      ) : null}
    </td>
  );
}

/**
 * The schedule: who is working, when, and on what.
 *
 * Rows are technicians rather than hours, because the question a dispatcher
 * asks is "who can take this?" - and the shaded working hours behind each row
 * answer it before anyone opens a job. Work that has nobody yet sits in its own
 * row at the top, where it cannot be missed.
 */
export function ScheduleClient({
  timeZone,
  team,
  canBook,
}: {
  timeZone: string;
  team: boolean;
  canBook: boolean;
}) {
  const [view, setView] = useState<View>("day");
  const [anchor, setAnchor] = useState(() => todayIn(timeZone));
  const [employeeId, setEmployeeId] = useState("");
  const [status, setStatus] = useState("");

  const start = view === "day" ? anchor : startOfWeek(anchor);
  const end = view === "day" ? anchor : addDays(start, 6);
  const dates = useMemo(
    () => Array.from({ length: view === "day" ? 1 : 7 }, (_, index) => addDays(start, index)),
    [start, view],
  );

  const params = { start, end, employee_id: employeeId || undefined, status: status || undefined };
  const query = useQuery<ScheduleFeed, ApiError>({
    queryKey: queryKeys.schedule.range(params),
    queryFn: () => {
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) if (value) search.set(key, String(value));
      return apiFetch<ScheduleFeed>(`schedule?${search.toString()}`);
    },
    placeholderData: (previous) => previous,
    refetchInterval: 60_000,
  });

  // Filter options come from the unfiltered lane list, so choosing a technician
  // never empties the menu you would use to choose someone else.
  const allLanes = useQuery<ScheduleFeed, ApiError>({
    queryKey: queryKeys.schedule.range({ start, end, lanesOnly: true }),
    queryFn: () => apiFetch<ScheduleFeed>(`schedule?start=${start}&end=${start}`),
    enabled: team,
    staleTime: 5 * 60_000,
  });

  const feed = query.data;
  const lanes = useMemo(() => feed?.lanes ?? [], [feed]);
  const entries = useMemo(() => feed?.entries ?? [], [feed]);
  const unassigned = entries.filter((entry) => entry.employee_id === null);
  const byEmployee = useMemo(() => {
    const grouped = new Map<string, ScheduleEntry[]>();
    for (const entry of entries) {
      if (!entry.employee_id) continue;
      grouped.set(entry.employee_id, [...(grouped.get(entry.employee_id) ?? []), entry]);
    }
    return grouped;
  }, [entries]);

  const onDate = (items: ScheduleEntry[], date: string) =>
    items.filter(
      (entry) =>
        localDateOf(entry.scheduled_start, timeZone) <= date &&
        localDateOf(entry.scheduled_end, timeZone) >= date,
    );

  const step = view === "day" ? 1 : 7;
  const heading =
    view === "day"
      ? formatLocalDate(anchor, { weekday: "long", month: "long", day: "numeric" })
      : `${formatLocalDate(start, { month: "short", day: "numeric" })} – ${formatLocalDate(end, { month: "short", day: "numeric", year: "numeric" })}`;
  const working = lanes.filter((lane) =>
    lane.days.some((day) => day.date === anchor && day.windows.length > 0),
  ).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title={team ? "Schedule" : "My Schedule"}
        description={
          team
            ? "Technicians, their working hours and their jobs. Times are shown in the business's timezone."
            : "Your working hours and the jobs assigned to you."
        }
        meta={
          feed && team && view === "day" ? (
            <span className="text-[13px] text-muted-foreground">
              {working} of {lanes.length} working · {entries.length} {entries.length === 1 ? "job" : "jobs"}
            </span>
          ) : null
        }
        action={
          canBook ? (
            <Button size="sm" render={<Link href="/bookings/new" />}>
              <CalendarPlus className="size-3.5" aria-hidden />
              New booking
            </Button>
          ) : null
        }
      />

      <Toolbar className="justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-md border bg-surface">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-none rounded-l-md"
              aria-label={view === "day" ? "Previous day" : "Previous week"}
              onClick={() => setAnchor(addDays(anchor, -step))}
            >
              <ChevronLeft className="size-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-none border-x px-3 text-[13px]"
              onClick={() => setAnchor(todayIn(timeZone))}
            >
              Today
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-none rounded-r-md"
              aria-label={view === "day" ? "Next day" : "Next week"}
              onClick={() => setAnchor(addDays(anchor, step))}
            >
              <ChevronRight className="size-4" aria-hidden />
            </Button>
          </div>
          <h2 className="ml-1 text-[15px] font-medium" aria-live="polite">
            {heading}
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Schedule view"
            value={view}
            onChange={setView}
            options={[
              { label: "Day", value: "day" },
              { label: "Week", value: "week" },
            ]}
          />
          {team ? (
            <FieldSelect label="Filter by technician" value={employeeId} onChange={setEmployeeId} className="w-44">
              <option value="">All technicians</option>
              {(allLanes.data?.lanes ?? lanes).map((lane) => (
                <option key={lane.employee_id} value={lane.employee_id}>
                  {lane.full_name}
                </option>
              ))}
            </FieldSelect>
          ) : null}
          <FieldSelect label="Filter by status" value={status} onChange={setStatus} className="w-36">
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </FieldSelect>
        </div>
      </Toolbar>

      {query.isError ? (
        <div className="rounded-lg border bg-surface">
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </div>
      ) : null}

      {query.isPending ? (
        <div className="space-y-px overflow-hidden rounded-lg border bg-surface">
          {[0, 1, 2, 3, 4].map((row) => (
            <div key={row} className="flex items-center gap-4 p-3">
              <Skeleton className="h-9 w-40" />
              <Skeleton className="h-9 flex-1" />
            </div>
          ))}
        </div>
      ) : null}

      {feed && lanes.length === 0 ? (
        <div className="rounded-lg border bg-surface">
          <EmptyState
            icon={UserRound}
            title={employeeId ? "That technician isn't active" : "No technicians yet"}
            description="Add employees with the services they perform, and their working hours will appear here."
          />
        </div>
      ) : null}

      {feed && lanes.length > 0 ? (
        <>
          {/* Tablet and desktop: technicians as rows. */}
          <div className="hidden overflow-hidden rounded-lg border bg-surface md:block">
            <div className="overflow-x-auto">
              {view === "day" ? (
                <div className="min-w-[860px]">
                  <div className="grid grid-cols-[200px_minmax(0,1fr)] border-b bg-muted/30">
                    <div className="border-r px-3 py-1.5 text-[12px] text-muted-foreground">Technician</div>
                    <div className="relative h-7">
                      {HOURS.map((hour) => (
                        <span
                          key={hour}
                          className="absolute top-1.5 -translate-x-1/2 text-[11px] tabular-nums text-muted-foreground"
                          style={{ left: `${percent(hour)}%` }}
                        >
                          {hour === DAY_START ? "" : minutesToLabel(hour).replace(":00", "")}
                        </span>
                      ))}
                    </div>
                  </div>
                  {team && unassigned.length > 0 ? (
                    <DayLane lane={null} entries={onDate(unassigned, anchor)} date={anchor} timeZone={timeZone} />
                  ) : null}
                  {lanes.map((lane) => (
                    <DayLane
                      key={lane.employee_id}
                      lane={lane}
                      entries={onDate(byEmployee.get(lane.employee_id) ?? [], anchor)}
                      date={anchor}
                      timeZone={timeZone}
                    />
                  ))}
                </div>
              ) : (
                <table className="w-full min-w-[980px] table-fixed border-collapse text-left">
                  <caption className="sr-only">Week schedule by technician</caption>
                  <thead>
                    <tr className="border-b bg-muted/30">
                      <th scope="col" className="w-[180px] px-3 py-2 text-[12px] font-normal text-muted-foreground">
                        Technician
                      </th>
                      {dates.map((date) => (
                        <th
                          key={date}
                          scope="col"
                          className={cn(
                            "border-l px-2 py-2 text-[12px] font-medium",
                            date === todayIn(timeZone) && "text-accent-solid",
                          )}
                        >
                          {formatLocalDate(date)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {team && unassigned.length > 0 ? (
                      <tr className="border-b">
                        <th scope="row" className="px-3 py-2 align-top text-[13px] font-medium text-status-pending">
                          Unassigned
                        </th>
                        {dates.map((date) => (
                          <WeekCell key={date} entries={onDate(unassigned, date)} hours="" timeZone={timeZone} />
                        ))}
                      </tr>
                    ) : null}
                    {lanes.map((lane) => (
                      <tr key={lane.employee_id} className="border-b last:border-b-0">
                        <th scope="row" className="px-3 py-2 align-top font-normal">
                          <span className="block truncate text-[13px] font-medium">{lane.full_name}</span>
                          <span className="block truncate text-[12px] text-muted-foreground">{lane.job_title}</span>
                        </th>
                        {dates.map((date) => {
                          const day = lane.days.find((candidate) => candidate.date === date);
                          const hours =
                            day && day.windows.length > 0
                              ? day.windows
                                  .map((w) => `${minutesToLabel(clockToMinutes(w.start)).replace(":00", "")}–${minutesToLabel(clockToMinutes(w.end)).replace(":00", "")}`)
                                  .join(", ")
                              : null;
                          return (
                            <WeekCell
                              key={date}
                              entries={onDate(byEmployee.get(lane.employee_id) ?? [], date)}
                              hours={hours ?? (day?.unavailable_reason && day.unavailable_reason !== "Not scheduled" ? day.unavailable_reason : null)}
                              timeZone={timeZone}
                            />
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/25 px-3 py-2 text-[12px] text-muted-foreground">
              {STATUS_OPTIONS.slice(0, 4).map((option) => (
                <span key={option.value} className="inline-flex items-center gap-1.5">
                  <span aria-hidden className={cn("h-3 w-3 rounded-sm border-l-[3px]", TONE[option.value])} />
                  {option.label}
                </span>
              ))}
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="h-3 w-4 rounded-sm bg-[repeating-linear-gradient(135deg,transparent,transparent_3px,var(--border)_3px,var(--border)_4px)]" />
                Not working
              </span>
              <span className="ml-auto">{feed.timezone.replace("_", " ")}</span>
            </div>
          </div>

          {/* Phones: an agenda, grouped by day, rather than a grid squeezed to nothing. */}
          <div className="space-y-4 md:hidden">
            {dates.map((date) => {
              const items = onDate(entries, date).sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
              return (
                <section key={date} className="space-y-2">
                  <h3 className="text-[13px] font-medium">
                    {formatLocalDate(date, { weekday: "long", month: "short", day: "numeric" })}
                  </h3>
                  {items.length === 0 ? (
                    <p className="rounded-lg border bg-surface px-3 py-3 text-[13px] text-muted-foreground">
                      Nothing scheduled.
                    </p>
                  ) : (
                    <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
                      {items.map((entry) => (
                        <li key={entry.id}>
                          <Link href={`/jobs/${entry.id}`} className="focus-ring block px-3 py-2.5">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-[13px] font-medium">{entry.service_name}</p>
                                <p className="truncate text-[12px] text-muted-foreground">
                                  {formatTime(entry.scheduled_start, timeZone)} · {formatDuration(entry.duration_minutes)} ·{" "}
                                  {entry.employee_name ?? "Unassigned"}
                                </p>
                                <p className="truncate text-[12px] text-muted-foreground">{entry.customer_name}</p>
                              </div>
                              <JobStatusBadge status={entry.status} />
                            </div>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>

          {entries.length === 0 ? (
            <div className="rounded-lg border bg-surface">
              <EmptyState
                icon={CalendarDays}
                title={status ? "No jobs with that status" : "Nothing booked in this range"}
                description={
                  status
                    ? "Try another status, or clear the filter."
                    : "Working hours are shown above; bookings will appear on them as they're scheduled."
                }
                action={
                  status ? (
                    <Button variant="outline" size="sm" onClick={() => setStatus("")}>
                      Clear filter
                    </Button>
                  ) : null
                }
              />
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
