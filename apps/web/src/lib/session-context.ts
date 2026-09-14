import { redirect } from "next/navigation";

import { accessFor, can, homePathFor, type Access } from "@/lib/permissions";
import { getActiveOrganizationId } from "@/lib/session";
import { serverFetchData } from "@/lib/server-api";
import type { Organization, Permission, SessionUser } from "@/lib/types";

export interface SessionContext {
  user: SessionUser;
  /** Null only for a platform administrator who belongs to no business. */
  organization: Organization | null;
  access: Access;
}

export interface TenantSessionContext extends SessionContext {
  organization: Organization;
}

/**
 * Resolves the caller for a server component, or redirects to sign-in.
 *
 * Permissions are narrowed to the active organization: a role held in another
 * business must not unlock anything here. This gates *rendering* only - the API
 * authorizes every request on its own.
 */
export async function requireSession(): Promise<SessionContext> {
  const user = await serverFetchData<SessionUser>("auth/me");
  // A cookie can outlive the session it names; send the visitor back to sign in.
  if (!user) redirect("/login");

  let organization: Organization | null = null;
  if (user.memberships.length > 0) {
    organization = await serverFetchData<Organization>("organizations/current");
    if (!organization) redirect("/login");
  }

  const activeOrganizationId = (await getActiveOrganizationId()) ?? organization?.id ?? null;
  return { user, organization, access: accessFor(user, activeOrganizationId) };
}

/** A session inside a business. Anyone without one goes to where they belong. */
export async function requireTenantSession(): Promise<TenantSessionContext> {
  const context = await requireSession();
  if (!context.organization) redirect(homePathFor(context.access));
  return context as TenantSessionContext;
}

/** Same, but sends anyone without one of `wanted` to their own start page. */
export async function requirePermission(...wanted: Permission[]): Promise<TenantSessionContext> {
  const context = await requireTenantSession();
  if (!can(context.access, ...wanted)) redirect(homePathFor(context.access));
  return context;
}

export async function requirePlatformAdmin(): Promise<SessionContext> {
  const context = await requireSession();
  if (!context.access.isPlatformAdmin) redirect(homePathFor(context.access));
  return context;
}
