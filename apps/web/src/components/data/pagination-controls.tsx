"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PageMeta } from "@/lib/types";

/**
 * The footer of a table: where you are in the set, and how to move.
 *
 * Lives inside the table's panel rather than floating below it, so a long list
 * reads as one object. The range is spelled out because "page 2 of 9" alone
 * never answers "how many are there".
 */
export function PaginationControls({
  meta,
  onPageChange,
  noun = "results",
}: {
  meta: PageMeta;
  onPageChange: (page: number) => void;
  noun?: string;
}) {
  if (meta.total === 0) return null;

  const first = (meta.page - 1) * meta.page_size + 1;
  const last = Math.min(meta.page * meta.page_size, meta.total);

  return (
    <div className="flex w-full items-center justify-between gap-4">
      <p className="text-[12px] text-muted-foreground">
        <span className="tabular-nums text-foreground">
          {first}–{last}
        </span>{" "}
        of <span className="tabular-nums text-foreground">{meta.total}</span> {noun}
      </p>

      {meta.pages > 1 ? (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[13px]"
            disabled={meta.page <= 1}
            onClick={() => onPageChange(meta.page - 1)}
          >
            <ChevronLeft className="size-3.5" aria-hidden />
            Previous
          </Button>
          {/* Compact on screen, spelled out for a screen reader. aria-label on
              a span is not reliably announced; a visually hidden phrase is. */}
          <span className="px-1 text-[12px] tabular-nums text-muted-foreground">
            <span className="sr-only">
              Page {meta.page} of {meta.pages}
            </span>
            <span aria-hidden>
              {meta.page} / {meta.pages}
            </span>
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[13px]"
            disabled={meta.page >= meta.pages}
            onClick={() => onPageChange(meta.page + 1)}
          >
            Next
            <ChevronRight className="size-3.5" aria-hidden />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
