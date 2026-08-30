/** Display formatting shared across pages, so money and durations look the same everywhere. */

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const currencyPrecise = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function formatPrice(value: string | number, { precise = false } = {}): string {
  const amount = typeof value === "string" ? Number.parseFloat(value) : value;
  if (Number.isNaN(amount)) return "—";
  const hasCents = Math.round(amount * 100) % 100 !== 0;
  return precise || hasCents ? currencyPrecise.format(amount) : currency.format(amount);
}

/** 45 -> "45 min", 240 -> "4 hr", 150 -> "2 hr 30 min" */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`;
}

export function formatDate(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone,
  }).format(new Date(iso));
}

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  const letters = parts.slice(0, 2).map((part) => part[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

/** "Sat, Sep 5" */
export function formatDayLabel(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone,
  }).format(new Date(iso));
}

/** "10:00 AM" */
export function formatTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

/** "Sat, Sep 5 · 10:00 AM – 12:30 PM" */
export function formatWindow(startIso: string, endIso: string, timeZone?: string): string {
  return `${formatDayLabel(startIso, timeZone)} · ${formatTime(startIso, timeZone)} – ${formatTime(
    endIso,
    timeZone,
  )}`;
}

/** "in 3 days" / "2 hours ago" - coarse on purpose, no ticking clock. */
export function formatRelative(iso: string): string {
  const diffMs = new Date(iso).getTime() - Date.now();
  const formatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  for (const [unit, ms] of units) {
    const value = Math.trunc(diffMs / ms);
    if (Math.abs(value) >= 1) return formatter.format(value, unit);
  }
  return "now";
}

export function isPast(iso: string): boolean {
  return new Date(iso).getTime() < Date.now();
}
