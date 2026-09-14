import {
  Activity,
  Building2,
  CalendarClock,
  CalendarDays,
  CalendarPlus,
  ClipboardList,
  LayoutDashboard,
  Settings,
  Tags,
  UserRound,
  Users,
  UserSquare,
  Wrench,
} from "lucide-react";

import { can, type Access } from "@/lib/permissions";
import type { Permission } from "@/lib/types";

/**
 * Navigation is grouped by what a person is doing, not by entity type: the work
 * of the day, then the records behind it, then running the business.
 */
export type NavGroup = "work" | "records" | "business" | "platform";

export interface NavItem {
  href: string;
  icon: typeof LayoutDashboard;
  group: NavGroup;
  /** Shown to anyone holding at least one of these. */
  permissions: Permission[];
  /** Hidden from anyone holding one of these (a wider view of the same thing). */
  hiddenWith?: Permission[];
  /** The first rule whose permissions match names the item; `label` otherwise. */
  labels?: { permissions: Permission[]; label: string }[];
  label: string;
}

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: "work", label: "Operations" },
  { id: "records", label: "Records" },
  { id: "business", label: "Business" },
  { id: "platform", label: "Platform" },
];

/**
 * One list for all seven roles, filtered by the permissions the API granted.
 *
 *   Owner       Dashboard, Schedule, Bookings, Jobs, Customers, Employees, Services, Activity, Settings
 *   Manager     the same, with Settings read-only
 *   Dispatcher  Dashboard, Schedule, Bookings, Jobs, Customers
 *   Technician  My Schedule, My Jobs, My Availability
 *   Customer    My Bookings, Book Service, Profile
 *   Analyst     Dashboard, Schedule, Bookings, Jobs, Customers, Employees, Services, Activity, Settings (read-only)
 *   Platform    Businesses
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, group: "work", permissions: ["dashboard:read"] },
  {
    label: "Schedule",
    href: "/schedule",
    icon: CalendarDays,
    group: "work",
    permissions: ["schedule:read", "schedule:own"],
    labels: [{ permissions: ["schedule:read"], label: "Schedule" }, { permissions: ["schedule:own"], label: "My Schedule" }],
  },
  {
    label: "Bookings",
    href: "/bookings",
    icon: ClipboardList,
    group: "work",
    permissions: ["bookings:read", "bookings:own"],
    labels: [{ permissions: ["bookings:read"], label: "Bookings" }, { permissions: ["bookings:own"], label: "My Bookings" }],
  },
  {
    label: "Book Service",
    href: "/bookings/new",
    icon: CalendarPlus,
    group: "work",
    permissions: ["bookings:own"],
    hiddenWith: ["bookings:write", "bookings:read"],
  },
  {
    label: "Jobs",
    href: "/jobs",
    icon: Wrench,
    group: "work",
    permissions: ["jobs:read", "jobs:work"],
    labels: [{ permissions: ["jobs:read"], label: "Jobs" }, { permissions: ["jobs:work"], label: "My Jobs" }],
  },
  {
    label: "My Availability",
    href: "/availability",
    icon: CalendarClock,
    group: "work",
    permissions: ["availability:own"],
    hiddenWith: ["availability:manage"],
  },

  { label: "Customers", href: "/customers", icon: Users, group: "records", permissions: ["customers:read"] },
  { label: "Employees", href: "/employees", icon: UserSquare, group: "records", permissions: ["employees:write", "services:read_retired"] },
  { label: "Services", href: "/services", icon: Tags, group: "records", permissions: ["services:write", "services:read_retired"] },

  { label: "Activity", href: "/activity", icon: Activity, group: "business", permissions: ["audit:read"] },
  { label: "Settings", href: "/settings", icon: Settings, group: "business", permissions: ["members:read", "organization:manage"] },
  {
    label: "Profile",
    href: "/profile",
    icon: UserRound,
    group: "work",
    permissions: ["bookings:own"],
    hiddenWith: ["bookings:read"],
  },

  { label: "Businesses", href: "/platform", icon: Building2, group: "platform", permissions: ["platform:tenants"] },
];

function labelFor(item: NavItem, access: Access): string {
  const rule = item.labels?.find((candidate) => can(access, ...candidate.permissions));
  return rule?.label ?? item.label;
}

export function navItemsFor(access: Access): NavItem[] {
  return NAV_ITEMS.filter(
    (item) =>
      can(access, ...item.permissions) && !(item.hiddenWith && can(access, ...item.hiddenWith)),
  ).map((item) => ({ ...item, label: labelFor(item, access) }));
}

/** The same list, split into the groups the sidebar renders. Empty groups drop out. */
export function navGroupsFor(access: Access): { label: string; items: NavItem[] }[] {
  const visible = navItemsFor(access);
  return NAV_GROUPS.map((group) => ({
    label: group.label,
    items: visible.filter((item) => item.group === group.id),
  })).filter((group) => group.items.length > 0);
}
