import {
  Activity,
  CalendarClock,
  BarChart3,
  CalendarDays,
  ClipboardList,
  Car,
  LayoutDashboard,
  Settings,
  Sparkles,
  Users,
  UserSquare,
  Wrench,
} from "lucide-react";

import type { Role } from "@/lib/types";

/**
 * Navigation is grouped by what a person is doing, not by entity type: the work
 * of the day, then the records behind it, then the shop itself. A flat list of
 * eleven links makes every destination look equally likely.
 */
export type NavGroup = "work" | "records" | "shop";

export interface NavItem {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
  roles: Role[];
  group: NavGroup;
  /** Set until the page exists, so the sidebar never links somewhere that 404s. */
  comingSoon?: boolean;
}

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: "work", label: "Today" },
  { id: "records", label: "Records" },
  { id: "shop", label: "Shop" },
];

/** Sidebar sections (PRD 23), filtered to what each role may actually open. */
export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard, group: "work", roles: ["ADMIN", "EMPLOYEE", "CUSTOMER"] },
  { label: "Bookings", href: "/bookings", icon: ClipboardList, group: "work", roles: ["ADMIN", "CUSTOMER"] },
  { label: "Jobs", href: "/jobs", icon: Wrench, group: "work", roles: ["ADMIN", "EMPLOYEE"] },
  { label: "Calendar", href: "/calendar", icon: CalendarDays, group: "work", roles: ["ADMIN", "EMPLOYEE"] },

  { label: "Customers", href: "/customers", icon: Users, group: "records", roles: ["ADMIN"] },
  { label: "Vehicles", href: "/vehicles", icon: Car, group: "records", roles: ["ADMIN", "CUSTOMER"] },
  { label: "Activity", href: "/activity", icon: Activity, group: "records", roles: ["ADMIN"] },

  { label: "Team", href: "/employees", icon: UserSquare, group: "shop", roles: ["ADMIN"] },
  { label: "Availability", href: "/availability", icon: CalendarClock, group: "shop", roles: ["ADMIN", "EMPLOYEE"] },
  { label: "Services", href: "/services", icon: Sparkles, group: "shop", roles: ["ADMIN"] },
  { label: "Analytics", href: "/analytics", comingSoon: true, icon: BarChart3, group: "shop", roles: ["ADMIN"] },
  { label: "Settings", href: "/settings", comingSoon: true, icon: Settings, group: "shop", roles: ["ADMIN", "EMPLOYEE", "CUSTOMER"] },
];

export function navItemsForRoles(roles: Role[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => !item.comingSoon && item.roles.some((role) => roles.includes(role)),
  );
}

/** The same list, split into the groups the sidebar renders. Empty groups drop out. */
export function navGroupsForRoles(roles: Role[]): { label: string; items: NavItem[] }[] {
  const visible = navItemsForRoles(roles);
  return NAV_GROUPS.map((group) => ({
    label: group.label,
    items: visible.filter((item) => item.group === group.id),
  })).filter((group) => group.items.length > 0);
}
