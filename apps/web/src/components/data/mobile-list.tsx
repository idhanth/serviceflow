import { cn } from "@/lib/utils";

/**
 * The phone-sized rendering of a table.
 *
 * A six-column operational table works on a laptop and not on a handset: at
 * 390px it becomes a horizontal scroll where the status and the price - the two
 * things being looked for - are off screen. The same records stack instead,
 * with the primary fact first and the rest underneath.
 *
 * Desktop keeps the table. This is not a card-per-row layout creeping in; it is
 * the same data at a width where rows cannot exist.
 */
export function MobileList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("divide-y md:hidden", className)}>{children}</div>;
}

export function MobileRow({
  title,
  subtitle,
  meta,
  trailing,
  onClick,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  meta?: React.ReactNode;
  trailing?: React.ReactNode;
  onClick?: () => void;
  className?: string;
}) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-0.5">
          <div className="truncate text-[14px] font-medium">{title}</div>
          {subtitle ? (
            <div className="truncate text-[13px] text-muted-foreground">{subtitle}</div>
          ) : null}
        </div>
        {trailing ? <div className="shrink-0 text-right">{trailing}</div> : null}
      </div>
      {meta ? <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div> : null}
    </>
  );

  if (!onClick) return <div className={cn("px-4 py-3", className)}>{content}</div>;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "focus-ring block w-full px-4 py-3 text-left transition-colors duration-75 hover:bg-muted/40",
        className,
      )}
    >
      {content}
    </button>
  );
}
