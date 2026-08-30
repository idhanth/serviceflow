import { Badge } from "@/components/ui/badge";
import type { BookingStatus, JobStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Active/inactive badge. The label carries the meaning, not the colour alone
 * (PRD 25), and both palettes stay legible in dark mode.
 */
export function ActiveBadge({ active, activeLabel = "Active", inactiveLabel = "Inactive" }: {
  active: boolean;
  activeLabel?: string;
  inactiveLabel?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 font-medium",
        active
          ? "border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:border-emerald-400/30 dark:text-emerald-300"
          : "border-muted-foreground/25 bg-muted text-muted-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          active ? "bg-emerald-600 dark:bg-emerald-400" : "bg-muted-foreground/60",
        )}
      />
      {active ? activeLabel : inactiveLabel}
    </Badge>
  );
}


/**
 * Booking and job status badges (PRD 25). Each carries a readable label so the
 * meaning never depends on colour alone, and every palette is picked to stay
 * legible in both themes.
 */
const TONES = {
  neutral: "border-muted-foreground/25 bg-muted text-muted-foreground",
  amber:
    "border-amber-600/30 bg-amber-500/10 text-amber-700 dark:border-amber-400/30 dark:text-amber-300",
  emerald:
    "border-emerald-600/30 bg-emerald-500/10 text-emerald-700 dark:border-emerald-400/30 dark:text-emerald-300",
  blue: "border-blue-600/30 bg-blue-500/10 text-blue-700 dark:border-blue-400/30 dark:text-blue-300",
  rose: "border-rose-600/30 bg-rose-500/10 text-rose-700 dark:border-rose-400/30 dark:text-rose-300",
} as const;

const DOTS = {
  neutral: "bg-muted-foreground/60",
  amber: "bg-amber-600 dark:bg-amber-400",
  emerald: "bg-emerald-600 dark:bg-emerald-400",
  blue: "bg-blue-600 dark:bg-blue-400",
  rose: "bg-rose-600 dark:bg-rose-400",
} as const;

type Tone = keyof typeof TONES;

const BOOKING_TONES: Record<BookingStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "Pending review", tone: "amber" },
  CONFIRMED: { label: "Confirmed", tone: "emerald" },
  REJECTED: { label: "Declined", tone: "rose" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

const JOB_TONES: Record<JobStatus, { label: string; tone: Tone }> = {
  ASSIGNED: { label: "Assigned", tone: "blue" },
  IN_PROGRESS: { label: "In progress", tone: "amber" },
  COMPLETED: { label: "Completed", tone: "emerald" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 whitespace-nowrap font-medium", TONES[tone])}>
      <span aria-hidden className={cn("size-1.5 rounded-full", DOTS[tone])} />
      {label}
    </Badge>
  );
}

export function BookingStatusBadge({ status }: { status: BookingStatus }) {
  return <StatusPill {...BOOKING_TONES[status]} />;
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <StatusPill {...JOB_TONES[status]} />;
}
