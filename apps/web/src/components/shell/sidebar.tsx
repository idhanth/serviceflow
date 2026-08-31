"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { navGroupsForRoles } from "@/components/shell/nav-items";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Dense, grouped navigation.
 *
 * Rows are 30px, not 40: this is a tool someone keeps open all day, and the
 * sidebar's job is to disappear. The active row is marked with the product's one
 * accent colour and a left rule rather than a filled pill, so the current place
 * is obvious without the nav shouting.
 */
export function SidebarNav({ roles, onNavigate }: { roles: Role[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  const groups = navGroupsForRoles(roles);

  return (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground/70">
            {group.label}
          </p>
          {group.items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "focus-ring group relative flex h-[30px] items-center gap-2.5 rounded-md px-2",
                  "text-[13px] transition-colors duration-100",
                  active
                    ? "bg-accent font-medium text-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )}
              >
                {active ? (
                  <span
                    aria-hidden
                    className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent-solid"
                  />
                ) : null}
                <Icon
                  className={cn(
                    "size-4 shrink-0 transition-colors duration-100",
                    active ? "text-accent-solid" : "text-muted-foreground/70 group-hover:text-foreground",
                  )}
                  aria-hidden
                />
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
