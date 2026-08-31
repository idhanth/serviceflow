import type { BookingStatus, JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * One status system for the whole product.
 *
 * Every state in ServiceFlow maps to one of six meanings, and each meaning has
 * exactly one colour drawn from the token layer - so "waiting on us" looks the
 * same on a booking, a job and a feed entry. Colour is never the only signal:
 * each has a written label.
 *
 * The default rendering is a dot and a word, not a chip. A table of twenty rows
 * with twenty filled pills reads as decoration; a column of small dots reads as
 * a status column. Chips are reserved for the one place a record's state is the
 * headline - a detail header or a review sheet.
 */
type Tone = "pending" | "info" | "active" | "done" | "danger" | "muted";

const DOT: Record<Tone, string> = {
  pending: "bg-status-pending",
  info: "bg-status-info",
  active: "bg-status-active",
  done: "bg-status-done",
  danger: "bg-status-danger",
  muted: "bg-status-muted/60",
};

const CHIP: Record<Tone, string> = {
  pending: "border-status-pending/25 bg-status-pending/10 text-status-pending",
  info: "border-status-info/25 bg-status-info/10 text-status-info",
  active: "border-status-active/25 bg-status-active/10 text-status-active",
  done: "border-status-done/25 bg-status-done/10 text-status-done",
  danger: "border-status-danger/25 bg-status-danger/10 text-status-danger",
  muted: "border-border bg-muted text-muted-foreground",
};

const BOOKING: Record<BookingStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "Pending review", tone: "pending" },
  CONFIRMED: { label: "Confirmed", tone: "info" },
  REJECTED: { label: "Declined", tone: "danger" },
  CANCELLED: { label: "Cancelled", tone: "muted" },
};

const JOB: Record<JobStatus, { label: string; tone: Tone }> = {
  ASSIGNED: { label: "Assigned", tone: "info" },
  IN_PROGRESS: { label: "In progress", tone: "active" },
  COMPLETED: { label: "Completed", tone: "done" },
  CANCELLED: { label: "Cancelled", tone: "muted" },
};

export function Status({
  label,
  tone,
  variant = "inline",
  className,
}: {
  label: string;
  tone: Tone;
  variant?: "inline" | "chip";
  className?: string;
}) {
  if (variant === "chip") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 whitespace-nowrap rounded border px-1.5 py-0.5",
          "text-[12px] font-medium",
          CHIP[tone],
          className,
        )}
      >
        <span aria-hidden className={cn("status-dot", DOT[tone])} />
        {label}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 whitespace-nowrap text-[13px] text-foreground",
        className,
      )}
    >
      <span aria-hidden className={cn("status-dot", DOT[tone])} />
      {label}
    </span>
  );
}

export function BookingStatusBadge({
  status,
  variant,
}: {
  status: BookingStatus;
  variant?: "inline" | "chip";
}) {
  return <Status {...BOOKING[status]} variant={variant} />;
}

export function JobStatusBadge({
  status,
  variant,
}: {
  status: JobStatus;
  variant?: "inline" | "chip";
}) {
  return <Status {...JOB[status]} variant={variant} />;
}

/** Whether a record is in use. Same vocabulary as every other state. */
export function ActiveBadge({
  active,
  activeLabel = "Active",
  inactiveLabel = "Inactive",
  variant,
}: {
  active: boolean;
  activeLabel?: string;
  inactiveLabel?: string;
  variant?: "inline" | "chip";
}) {
  return (
    <Status
      label={active ? activeLabel : inactiveLabel}
      tone={active ? "done" : "muted"}
      variant={variant}
    />
  );
}
