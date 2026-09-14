/**
 * Calendar-date arithmetic in the business's timezone.
 *
 * A dispatcher in Chicago looking at "today" means Chicago's today, whatever
 * timezone their laptop is set to. Dates are handled as "YYYY-MM-DD" strings and
 * instants as ISO strings; nothing here relies on the browser's own zone.
 */

export function todayIn(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
}

export function localDateOf(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));
}

export function addDays(date: string, days: number): string {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

/** Monday of the week containing `date`. */
export function startOfWeek(date: string): string {
  const weekday = (new Date(`${date}T12:00:00Z`).getUTCDay() + 6) % 7;
  return addDays(date, -weekday);
}

/** Minutes after local midnight at which an instant falls, in `timeZone`. */
export function minutesIntoDay(iso: string, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? 0);
  return hour * 60 + minute;
}

/** "08:30" -> 510 */
export function clockToMinutes(clock: string): number {
  const [hour, minute] = clock.split(":").map(Number);
  return hour * 60 + (minute || 0);
}

/** 510 -> "8:30 AM" */
export function minutesToLabel(minutes: number): string {
  const hour = Math.floor(minutes / 60) % 24;
  const minute = minutes % 60;
  const suffix = hour < 12 ? "AM" : "PM";
  return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

export function formatLocalDate(
  date: string,
  options: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric" },
): string {
  return new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(
    new Date(`${date}T12:00:00Z`),
  );
}

/**
 * A local wall-clock date and time in `timeZone`, as an ISO instant.
 *
 * `datetime-local` inputs give "2026-09-15T14:00" with no zone. The business
 * books in its own timezone, so the offset is found for that zone on that date
 * - which also gets daylight-saving transitions right.
 */
export function zonedTimeToIso(local: string, timeZone: string): string {
  const [datePart, timePart = "00:00"] = local.split("T");
  const guess = new Date(`${datePart}T${timePart}:00Z`);
  const offsetAt = (instant: Date) => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(instant);
    const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
    const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
    return asUtc - instant.getTime();
  };
  const first = new Date(guess.getTime() - offsetAt(guess));
  const corrected = new Date(guess.getTime() - offsetAt(first));
  return corrected.toISOString();
}
