import type { MembershipSummary, Permission, Role, SessionUser } from "@/lib/types";

/**
 * What the signed-in person may do, as the API told us.
 *
 * The frontend never derives permissions from role names on its own: the list
 * comes from /auth/me, so there is one source of truth (the API's permission
 * table) and the UI can only ever hide less than the server refuses. Hiding a
 * button is a courtesy; every request is still authorized server-side.
 */
export interface Access {
  roles: Role[];
  permissions: Permission[];
  isPlatformAdmin: boolean;
}

export function accessFor(user: SessionUser, organizationId: string | null): Access {
  const memberships: MembershipSummary[] = organizationId
    ? user.memberships.filter((membership) => membership.organization_id === organizationId)
    : [];
  const permissions = new Set<Permission>(user.platform_permissions ?? []);
  for (const membership of memberships) {
    for (const permission of membership.permissions) permissions.add(permission);
  }
  return {
    roles: memberships.map((membership) => membership.role),
    permissions: [...permissions],
    isPlatformAdmin: user.is_platform_admin,
  };
}

/** True when `access` holds at least one of `wanted`. */
export function can(access: Pick<Access, "permissions">, ...wanted: Permission[]): boolean {
  return wanted.some((permission) => access.permissions.includes(permission));
}

export const ROLE_LABELS: Record<Role | "PLATFORM_ADMIN", string> = {
  PLATFORM_ADMIN: "Platform admin",
  OWNER: "Business owner",
  MANAGER: "Manager",
  DISPATCHER: "Dispatcher",
  TECHNICIAN: "Technician",
  CUSTOMER: "Customer",
  ANALYST: "Analyst (read-only)",
};

const ROLE_ORDER: Role[] = ["OWNER", "MANAGER", "DISPATCHER", "ANALYST", "TECHNICIAN", "CUSTOMER"];

/** The role to name someone by when they hold several in one business. */
export function primaryRoleLabel(access: Access): string {
  const role = ROLE_ORDER.find((candidate) => access.roles.includes(candidate));
  if (role) return ROLE_LABELS[role];
  return access.isPlatformAdmin ? ROLE_LABELS.PLATFORM_ADMIN : "Member";
}

/** Where each kind of person starts: the screen they are responsible for. */
export function homePathFor(access: Access): string {
  if (can(access, "dashboard:read")) return "/dashboard";
  if (can(access, "schedule:own", "jobs:work")) return "/schedule";
  if (can(access, "bookings:own")) return "/bookings";
  if (access.isPlatformAdmin) return "/platform";
  return "/login";
}
