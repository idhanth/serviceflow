"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/data/page-header";
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

const STATUS_TONES: Record<JobStatus, string> = {
  ASSIGNED: "border-blue-600/40 bg-blue-500/10 hover:bg-blue-500/20",
  IN_PROGRESS: "border-amber-600/40 bg-amber-500/15 hover:bg-amber-500/25",
  COMPLETED: "border-emerald-600/40 bg-emerald-500/10 hover:bg-emerald-500/20",
  CANCELLED: "border-muted-foreground/30 bg-muted opacity-60 hover:opacity-80",
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

function localDayKey(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));
}

function EventCard({ event, compact }: { event: CalendarEvent; compact?: boolean }) {
  return (
    <Link
      href={`/jobs/${event.id}`}
      className={cn(
        "block h-full overflow-hidden rounded-md border px-2 py-1 text-left transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        STATUS_TONES[event.status],
      )}
    >
      <p className="truncate text-xs font-medium">
        {formatTime(event.scheduled_start)} {event.service_name}
      </p>
      {!compact ? (
        <>
          <p className="truncate text-xs text-muted-foreground">{event.customer_name}</p>
          <p className="truncate text-xs text-muted-foreground">{event.employee_name}</p>
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
          <Button
            variant="outline"
            size="icon"
            aria-label={view === "day" ? "Previous day" : "Previous week"}
            onClick={() => setAnchor(addDays(anchor, view === "day" ? -1 : -7))}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAnchor(new Date())}>
            Today
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label={view === "day" ? "Next day" : "Next week"}
            onClick={() => setAnchor(addDays(anchor, view === "day" ? 1 : 7))}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
          <span className="ml-1 text-sm font-medium">
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
          <div role="group" aria-label="Calendar view" className="flex rounded-lg border p-0.5">
            {(["day", "week"] as const).map((option) => (
              <Button
                key={option}
                size="sm"
                variant={view === option ? "secondary" : "ghost"}
                aria-pressed={view === option}
                onClick={() => setView(option)}
                className="capitalize"
              >
                {option}
              </Button>
            ))}
          </div>

          {isAdmin ? (
            <select
              aria-label="Filter by employee"
              className="h-9 rounded-lg border bg-background px-2 text-sm"
              value={employeeId}
              onChange={(event) => setEmployeeId(event.target.value)}
            >
              <option value="">All employees</option>
              {(employees.data?.data ?? []).map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.user.full_name}
                </option>
              ))}
            </select>
          ) : null}

          <select
            aria-label="Filter by service"
            className="h-9 rounded-lg border bg-background px-2 text-sm"
            value={serviceId}
            onChange={(event) => setServiceId(event.target.value)}
          >
            <option value="">All services</option>
            {(services.data?.data ?? []).map((service) => (
              <option key={service.id} value={service.id}>
                {service.name}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by status"
            className="h-9 rounded-lg border bg-background px-2 text-sm"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="ASSIGNED">Assigned</option>
            <option value="IN_PROGRESS">In progress</option>
            <option value="COMPLETED">Completed</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
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
              <div className={cn("grid min-w-[720px]", view === "day" ? "grid-cols-[64px_1fr]" : "grid-cols-[64px_repeat(7,1fr)]")}>
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
                      {byDay[key].map((event) => {
                        const { top, height } = position(event, timeZone, key);
                        return (
                          <div
                            key={`${key}-${event.id}`}
                            className="absolute inset-x-1"
                            style={{ top: `${top}%`, height: `${height}%` }}
                          >
                            <EventCard event={event} compact={view === "week"} />
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
                          className="block rounded-xl border bg-card p-4 transition-colors duration-150 hover:bg-accent/40"
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
