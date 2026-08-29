import { Badge } from "@/components/ui/badge";
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
