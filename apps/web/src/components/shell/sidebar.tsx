"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { navGroupsFor } from "@/components/shell/nav-items";
import type { Access } from "@/lib/permissions";
import { cn } from "@/lib/utils";

/**
 * Dense, grouped navigation.
 *
 * Rows are 30px, not 40: this is a tool someone keeps open all day, and the
 * sidebar's job is to disappear. The active row is marked with the product's one
 * accent colour and a left rule rather than a filled pill, so the current place
 * is obvious without the nav shouting.
 */
export function SidebarNav({ access, onNavigate }: { access: Access; onNavigate?: () => void }) {
  const pathname = usePathname();
  const groups = navGroupsFor(access);
  // The most specific matching link is the current page, so "Book Service"
  // (/bookings/new) is not also shown as "My Bookings" (/bookings).
  const current = groups
    .flatMap((group) => group.items)
    .filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
  const showGroupLabels = groups.length > 1;

  return (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          {showGroupLabels ? (
            <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground/70">
              {group.label}
            </p>
          ) : null}
          {group.items.map((item) => {
            const active = item.href === current;
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
