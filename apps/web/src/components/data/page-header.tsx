import { cn } from "@/lib/utils";

/**
 * The top of every page: what this is, optionally one line of context, and the
 * single most likely action.
 *
 * 20px semibold, not 30px. This is operations software - the title orients you
 * and then gets out of the way, because the content below is the reason the
 * page exists.
 */
export function PageHeader({
  title,
  description,
  action,
  meta,
  className,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  /** Small facts that belong with the title - counts, a date range, a status. */
  meta?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-x-6 gap-y-3", className)}>
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">{title}</h1>
          {meta}
        </div>
        {description ? (
          <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </header>
  );
}

/**
 * A heading inside a page. One step down from the page title, and deliberately
 * quiet: sections are separated by space and a rule, not by another card.
 */
export function SectionHeader({
  title,
  description,
  action,
  className,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-end justify-between gap-4", className)}>
      <div className="space-y-0.5">
        <h2 className="text-[15px] font-medium leading-tight">{title}</h2>
        {description ? (
          <p className="text-[13px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/**
 * The strip under a page header holding search, filters and view switches.
 * Every list page uses this, so the controls sit in the same place everywhere.
 */
export function Toolbar({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>{children}</div>
  );
}
