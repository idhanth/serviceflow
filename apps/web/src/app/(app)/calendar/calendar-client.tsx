"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { FieldSelect } from "@/components/data/field-select";
import { PageHeader } from "@/components/data/page-header";
import { Segmented } from "@/components/data/segmented";
import { JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePagedResource } from "@/hooks/use-resource";
import { apiFetch, ApiError } from "@/lib/api-client";
import { formatDuration, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { CalendarEvent, CalendarFeed, Employee, JobStatus, Service } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY_START_HOUR = 6;
const DAY_END_HOUR = 22;
const HOUR_HEIGHT = 56;

type View = "day" | "week";

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

/** Monday-start week containing `value`. */
function startOfWeek(value: Date): Date {
  const day = (value.getDay() + 6) % 7;
  return addDays(value, -day);
}

/**
 * Events wear the product's status colours, carried on a left rule rather than
 * a filled block: a week of solid colour is a chart, not a schedule.
 */
const STATUS_TONES: Record<JobStatus, string> = {
  ASSIGNED: "border-l-status-info bg-status-info/[0.07] hover:bg-status-info/[0.13]",
  IN_PROGRESS: "border-l-status-active bg-status-active/[0.1] hover:bg-status-active/[0.16]",
  COMPLETED: "border-l-status-done bg-status-done/[0.07] hover:bg-status-done/[0.13]",
  CANCELLED: "border-l-border bg-muted/60 opacity-70 hover:opacity-90",
};

/**
 * Where an event sits in a day column, as a fraction of the visible hours.
 * Computed in the shop's timezone so the grid matches the schedule everyone
 * else is looking at.
 */
function position(event: CalendarEvent, timeZone: string, dayKey: string) {
  const minutesInto = (iso: string) => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date(iso));
    const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
    const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
    return hour * 60 + minute;
  };

  const localDay = (iso: string) =>
    new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));

  // Clamp to this column when an event spills across midnight.
  const startsToday = localDay(event.scheduled_start) === dayKey;
  const endsToday = localDay(event.scheduled_end) === dayKey;
  const from = startsToday ? minutesInto(event.scheduled_start) : 0;
  const to = endsToday ? minutesInto(event.scheduled_end) : 24 * 60;

  const windowStart = DAY_START_HOUR * 60;
  const windowMinutes = (DAY_END_HOUR - DAY_START_HOUR) * 60;
  const top = ((Math.max(from, windowStart) - windowStart) / windowMinutes) * 100;
  const height = ((Math.min(to, DAY_END_HOUR * 60) - Math.max(from, windowStart)) / windowMinutes) * 100;
  return { top, height: Math.max(height, 3) };
}

/**
 * Side-by-side placement for events that overlap in time.
 *
 * Without this, two jobs booked at the same hour are drawn on top of one
 * another and neither is readable - which is exactly the moment a scheduler
 * most needs to see both.
 */
function withLanes(events: CalendarEvent[]): { event: CalendarEvent; lane: number; lanes: number }[] {
  const ordered = [...events].sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
  const placed: { event: CalendarEvent; lane: number; lanes: number }[] = [];
  let cluster: typeof placed = [];
  let clusterEnd = "";

  const flush = () => {
    const lanes = cluster.reduce((max, item) => Math.max(max, item.lane + 1), 1);
    for (const item of cluster) item.lanes = lanes;
    placed.push(...cluster);
    cluster = [];
    clusterEnd = "";
  };

  for (const event of ordered) {
    // A new cluster starts as soon as an event begins after everything before
    // it has finished.
    if (cluster.length > 0 && event.scheduled_start >= clusterEnd) flush();

    const taken = new Set(
      cluster
        .filter((item) => item.event.scheduled_end > event.scheduled_start)
        .map((item) => item.lane),
    );
    let lane = 0;
    while (taken.has(lane)) lane += 1;

    cluster.push({ event, lane, lanes: 1 });
    if (event.scheduled_end > clusterEnd) clusterEnd = event.scheduled_end;
  }
  flush();
  return placed;
}

function localDayKey(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));
}

function EventCard({
  event,
  compact,
  timeZone,
  narrow,
}: {
  event: CalendarEvent;
  compact?: boolean;
  timeZone: string;
  /** Sharing its slot with another job, so there is room for one fact only. */
  narrow?: boolean;
}) {
  return (
    <Link
      href={`/jobs/${event.id}`}
      className={cn(
        "focus-ring block h-full overflow-hidden rounded-sm border-l-2 px-1.5 py-1 text-left",
        "transition-colors duration-75",
        STATUS_TONES[event.status],
      )}
    >
      {/* When two jobs share an hour there is no room for both the time and the
          service. The position on the grid already says when; the name is the
          part that cannot be inferred. */}
      <p className="truncate text-[11px] font-medium leading-tight">
        {narrow ? (
          event.service_name
        ) : (
          <>
            <span className="tabular-nums text-muted-foreground">
              {formatTime(event.scheduled_start, timeZone)}
            </span>{" "}
            {event.service_name}
          </>
        )}
      </p>
      {!compact ? (
        <>
          <p className="truncate text-[11px] leading-tight text-muted-foreground">
            {event.customer_name}
          </p>
          <p className="truncate text-[11px] leading-tight text-muted-foreground">
            {event.employee_name}
          </p>
        </>
      ) : null}
    </Link>
  );
}

export function CalendarClient({
  timeZone,
  isAdmin,
}: {
  timeZone: string;
  isAdmin: boolean;
}) {
  const [view, setView] = useState<View>("week");
  const [anchor, setAnchor] = useState(() => new Date());
  const [employeeId, setEmployeeId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [status, setStatus] = useState("");

  const days = useMemo(() => {
    const first = view === "day" ? anchor : startOfWeek(anchor);
    return Array.from({ length: view === "day" ? 1 : 7 }, (_, index) => addDays(first, index));
  }, [anchor, view]);

  const rangeStart = isoDate(days[0]);
  const rangeEnd = isoDate(days[days.length - 1]);

  const params = {
    start: rangeStart,
    end: rangeEnd,
    employee_id: employeeId || undefined,
    service_id: serviceId || undefined,
    status: status || undefined,
  };

  const query = useQuery<CalendarFeed, ApiError>({
    queryKey: queryKeys.calendar.range(params),
    queryFn: () => {
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value) search.set(key, String(value));
      }
      return apiFetch<CalendarFeed>(`calendar?${search.toString()}`);
    },
    placeholderData: (previous) => previous,
  });

  const employeeParams = { active: true, page_size: 100 };
  const employees = usePagedResource<Employee>(
    queryKeys.employees.list(employeeParams),
    "employees",
    employeeParams,
    { enabled: isAdmin },
  );
  const serviceParams = { page_size: 100 };
  const services = usePagedResource<Service>(
    queryKeys.services.list(serviceParams),
    "services",
    serviceParams,
  );

  const byDay = useMemo(() => {
    const grouped: Record<string, CalendarEvent[]> = {};
    for (const day of days) grouped[isoDate(day)] = [];
    for (const event of query.data?.data ?? []) {
      // A job can touch more than one column when it crosses local midnight.
      for (const day of days) {
        const key = isoDate(day);
        const startKey = localDayKey(event.scheduled_start, timeZone);
        const endKey = localDayKey(event.scheduled_end, timeZone);
        if (key >= startKey && key <= endKey) grouped[key].push(event);
      }
    }
    return grouped;
  }, [query.data, days, timeZone]);

  const hours = Array.from(
    { length: DAY_END_HOUR - DAY_START_HOUR },
    (_, index) => DAY_START_HOUR + index,
  );
  const total = query.data?.data.length ?? 0;

  const rangeLabel = new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: days[0].getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  }).format(days[0]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Calendar"
        description={isAdmin ? "Everything scheduled across the shop." : "Your schedule."}
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-2">
          {/* One joined control for moving through time, so the three parts read
              as a single instrument rather than three buttons. */}
          <div className="flex items-center rounded-md border bg-surface">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-none rounded-l-md"
              aria-label={view === "day" ? "Previous day" : "Previous week"}
              onClick={() => setAnchor(addDays(anchor, view === "day" ? -1 : -7))}
            >
              <ChevronLeft className="size-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-none border-x px-3 text-[13px]"
              onClick={() => setAnchor(new Date())}
            >
              Today
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 rounded-none rounded-r-md"
              aria-label={view === "day" ? "Next day" : "Next week"}
              onClick={() => setAnchor(addDays(anchor, view === "day" ? 1 : 7))}
            >
              <ChevronRight className="size-4" aria-hidden />
            </Button>
          </div>
          <span className="ml-1 text-[15px] font-medium">
            {view === "day"
              ? new Intl.DateTimeFormat("en-US", {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                }).format(days[0])
              : `Week of ${rangeLabel}`}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Calendar view"
            value={view}
            onChange={setView}
            options={[
              { label: "Day", value: "day" },
              { label: "Week", value: "week" },
            ]}
          />

          {isAdmin ? (
            <FieldSelect
              label="Filter by employee"
              value={employeeId}
              onChange={setEmployeeId}
              className="w-40"
            >
              <option value="">All employees</option>
              {(employees.data?.data ?? []).map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.user.full_name}
                </option>
              ))}
            </FieldSelect>
          ) : null}

          <FieldSelect
            label="Filter by service"
            value={serviceId}
            onChange={setServiceId}
            className="w-40"
          >
            <option value="">All services</option>
            {(services.data?.data ?? []).map((service) => (
              <option key={service.id} value={service.id}>
                {service.name}
              </option>
            ))}
          </FieldSelect>

          <FieldSelect
            label="Filter by status"
            value={status}
            onChange={setStatus}
            className="w-36"
          >
            <option value="">All statuses</option>
            <option value="ASSIGNED">Assigned</option>
            <option value="IN_PROGRESS">In progress</option>
            <option value="COMPLETED">Completed</option>
            <option value="CANCELLED">Cancelled</option>
          </FieldSelect>
        </div>
      </div>

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : null}

      {query.isPending ? (
        <Card className="p-5">
          <div className="space-y-2">
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <Skeleton key={row} className="h-12 w-full" />
            ))}
          </div>
        </Card>
      ) : null}

      {query.isSuccess && total === 0 ? (
        <Card>
          <EmptyState
            icon={CalendarDays}
            title="Nothing scheduled"
            description={
              employeeId || serviceId || status
                ? "No jobs match these filters in this range."
                : "Confirm a booking and it will appear here."
            }
            action={
              employeeId || serviceId || status ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setEmployeeId("");
                    setServiceId("");
                    setStatus("");
                  }}
                >
                  Clear filters
                </Button>
              ) : null
            }
          />
        </Card>
      ) : null}

      {query.data && total > 0 ? (
        <>
          {/* Desktop and tablet: a time grid. */}
          <Card className="hidden overflow-hidden p-0 md:block">
            <div className="overflow-x-auto">
              <div className={cn(
                    // A week needs room: squeezed into 90px columns the service
                    // names collapse to single letters, so the grid keeps a
                    // readable minimum and scrolls instead.
                    "grid",
                    view === "day"
                      ? "min-w-[420px] grid-cols-[64px_1fr]"
                      : "min-w-[1000px] grid-cols-[64px_repeat(7,1fr)]",
                  )}>
                <div className="border-b border-r bg-muted/30 p-2 text-xs text-muted-foreground">
                  {query.data.timezone.split("/").pop()?.replace("_", " ")}
                </div>
                {days.map((day) => (
                  <div
                    key={isoDate(day)}
                    className="border-b border-r p-2 text-center last:border-r-0"
                  >
                    <div className="text-xs text-muted-foreground">
                      {new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(day)}
                    </div>
                    <div className="text-sm font-medium">{day.getDate()}</div>
                  </div>
                ))}

                <div className="border-r">
                  {hours.map((hour) => (
                    <div
                      key={hour}
                      style={{ height: HOUR_HEIGHT }}
                      className="relative border-b text-right"
                    >
                      <span className="absolute -top-2 right-2 text-xs text-muted-foreground">
                        {hour % 12 || 12}
                        {hour < 12 ? "am" : "pm"}
                      </span>
                    </div>
                  ))}
                </div>

                {days.map((day) => {
                  const key = isoDate(day);
                  return (
                    <div key={key} className="relative border-r last:border-r-0">
                      {hours.map((hour) => (
                        <div key={hour} style={{ height: HOUR_HEIGHT }} className="border-b" />
                      ))}
                      {withLanes(byDay[key]).map(({ event, lane, lanes }) => {
                        const { top, height } = position(event, timeZone, key);
                        return (
                          <div
                            key={`${key}-${event.id}`}
                            className="absolute px-px"
                            style={{
                              top: `${top}%`,
                              height: `${height}%`,
                              left: `calc(${(lane / lanes) * 100}% + 2px)`,
                              width: `calc(${100 / lanes}% - 4px)`,
                            }}
                          >
                            <EventCard
                              event={event}
                              compact={view === "week"}
                              timeZone={timeZone}
                              narrow={lanes > 1 && view === "week"}
                            />
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          </Card>

          {/* Mobile: an agenda, rather than a grid squeezed to nothing. */}
          <div className="space-y-4 md:hidden">
            {days.map((day) => {
              const key = isoDate(day);
              const events = byDay[key];
              if (events.length === 0) return null;
              return (
                <section key={key} className="space-y-2">
                  <h2 className="text-sm font-medium">
                    {new Intl.DateTimeFormat("en-US", {
                      weekday: "long",
                      month: "short",
                      day: "numeric",
                    }).format(day)}
                  </h2>
                  <ul className="space-y-2">
                    {events.map((event) => (
                      <li key={`${key}-${event.id}`}>
                        <Link
                          href={`/jobs/${event.id}`}
                          className="block rounded-lg border bg-card p-4 transition-colors duration-150 hover:bg-accent/40"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate font-medium">{event.service_name}</p>
                              <p className="truncate text-sm text-muted-foreground">
                                {formatTime(event.scheduled_start, timeZone)} ·{" "}
                                {formatDuration(event.duration_minutes)}
                              </p>
                              <p className="truncate text-sm text-muted-foreground">
                                {event.customer_name} · {event.vehicle_name}
                              </p>
                              {isAdmin ? (
                                <p className="truncate text-sm text-muted-foreground">
                                  {event.employee_name}
                                </p>
                              ) : null}
                            </div>
                            <JobStatusBadge status={event.status} />
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </>
      ) : null}
    </div>
  );
}
