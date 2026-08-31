import { cn } from "@/lib/utils";

/**
 * The container a table or list sits in.
 *
 * A single hairline border on a white surface - no shadow, no nested cards, no
 * heavy radius. Elevation is for things that float above the page; a table is
 * the page.
 */
export function DataPanel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-lg border bg-surface", className)}>
      {children}
    </div>
  );
}

/** A footer strip inside a panel: counts on the left, pagination on the right. */
export function PanelFooter({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t bg-muted/25 px-3 py-2",
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * The primary cell in a row: the thing a person is scanning for, with its
 * supporting detail underneath in a quieter voice.
 */
export function PrimaryCell({
  title,
  subtitle,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="truncate font-medium text-foreground">{title}</div>
      {subtitle ? (
        <div className="truncate text-[12px] text-muted-foreground">{subtitle}</div>
      ) : null}
    </div>
  );
}
