"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * The numbers that matter, as one line.
 *
 * Not four bordered tiles with invented percentages: a shop lead wants to know
 * how much is waiting on them and how much is booked, and each number is a way
 * into the list behind it. Counts are real or they are not shown - there is no
 * trend arrow here because nothing in this product measures a trend.
 */
export interface Stat {
  label: string;
  value: number | string | undefined;
  href?: string;
  /** Draws attention when there is something to act on. */
  emphasis?: boolean;
}

export function StatStrip({ stats, className }: { stats: Stat[]; className?: string }) {
  return (
    // A grid, not a wrapping flex: wrapped flex children leave dividers that
    // stop halfway and rows that do not line up.
    <dl
      className={cn(
        "grid grid-cols-2 divide-x divide-y divide-border overflow-hidden rounded-lg border bg-surface",
        "sm:grid-cols-4 sm:divide-y-0",
        className,
      )}
    >
      {stats.map((stat) => {
        const body = (
          <>
            <dt className="text-[12px] text-muted-foreground">{stat.label}</dt>
            <dd
              className={cn(
                "text-[22px] font-semibold leading-none tabular-nums",
                stat.emphasis && stat.value ? "text-accent-solid" : "text-foreground",
              )}
            >
              {stat.value ?? "—"}
            </dd>
          </>
        );

        return (
          <div key={stat.label} className="min-w-0">
            {stat.href ? (
              <Link
                href={stat.href}
                className="focus-ring flex h-full flex-col justify-center gap-1.5 px-4 py-3 transition-colors duration-75 hover:bg-muted/40"
              >
                {body}
              </Link>
            ) : (
              <div className="flex h-full flex-col justify-center gap-1.5 px-4 py-3">{body}</div>
            )}
          </div>
        );
      })}
    </dl>
  );
}
