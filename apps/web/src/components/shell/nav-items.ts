import {
  Activity,
  BarChart3,
  CalendarDays,
  ClipboardList,
  Car,
  LayoutDashboard,
  Settings,
  Sparkles,
  Users,
  UserSquare,
} from "lucide-react";

import type { Role } from "@/lib/types";

export interface NavItem {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
  roles: Role[];
  /** Set until the page exists, so the sidebar never links somewhere that 404s. */
  comingSoon?: boolean;
}

/** Sidebar sections (PRD 23), filtered to what each role may actually open. */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, roles: ["ADMIN", "EMPLOYEE", "CUSTOMER"] },
  { label: "Bookings", href: "/bookings", icon: ClipboardList, roles: ["ADMIN", "CUSTOMER"] },
  { label: "Jobs", href: "/jobs", icon: Sparkles, roles: ["ADMIN", "EMPLOYEE"] },
  // Calendar lands in phase 4; analytics, activity and settings in later phases.
  { label: "Calendar", href: "/calendar", icon: CalendarDays, roles: ["ADMIN", "EMPLOYEE"], comingSoon: true },
  { label: "Vehicles", href: "/vehicles", icon: Car, roles: ["ADMIN", "CUSTOMER"] },
  { label: "Customers", href: "/customers", icon: Users, roles: ["ADMIN"] },
  { label: "Employees", href: "/employees", icon: UserSquare, roles: ["ADMIN"] },
  { label: "Services", href: "/services", icon: Sparkles, roles: ["ADMIN"] },
  { label: "Analytics", href: "/analytics", comingSoon: true, icon: BarChart3, roles: ["ADMIN"] },
  { label: "Activity", href: "/activity", comingSoon: true, icon: Activity, roles: ["ADMIN"] },
  { label: "Settings", href: "/settings", comingSoon: true, icon: Settings, roles: ["ADMIN", "EMPLOYEE", "CUSTOMER"] },
];

export function navItemsForRoles(roles: Role[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => !item.comingSoon && item.roles.some((role) => roles.includes(role)),
  );
}
