"use client";

import { cn } from "@/lib/utils";

/**
 * The filter control every list page uses.
 *
 * A single row of quiet buttons with one selected, rather than a floating pill
 * group: it reads as part of the table it filters. Counts sit beside the label
 * where we know them, because "Pending 15" answers the question the filter was
 * about to be used to ask.
 */
export interface SegmentedOption<T extends string> {
  label: string;
  value: T;
  count?: number;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (next: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md bg-muted/60 p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            className={cn(
              "focus-ring inline-flex h-7 shrink-0 items-center gap-1.5 rounded px-2.5 text-[13px]",
              "transition-colors duration-75",
              selected
                ? "bg-surface font-medium text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.06)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
            {/* The count is decorative: it repeats what the table's own footer
                already states ("1-20 of 22 bookings"), and folding it into the
                button's accessible name turns "Pending" into "Pending22". */}
            {option.count !== undefined ? (
              <span
                aria-hidden
                className={cn(
                  "text-[12px] tabular-nums",
                  selected ? "text-muted-foreground" : "text-muted-foreground/70",
                )}
              >
                {option.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
