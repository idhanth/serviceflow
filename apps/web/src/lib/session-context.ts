import { redirect } from "next/navigation";

import { getActiveOrganizationId } from "@/lib/session";
import { serverFetchData } from "@/lib/server-api";
import type { Organization, Role, SessionUser } from "@/lib/types";

export interface SessionContext {
  user: SessionUser;
  organization: Organization;
  roles: Role[];
}

/**
 * Resolves the caller for a server component, or redirects to sign-in.
 *
 * Roles are narrowed to the active organization: a role held elsewhere must not
 * unlock anything here. This gates *rendering* only - the API authorizes every
 * request on its own (PRD 61).
 */
export async function requireSession(): Promise<SessionContext> {
  const [user, organization] = await Promise.all([
    serverFetchData<SessionUser>("auth/me"),
    serverFetchData<Organization>("organizations/current"),
  ]);

  // A cookie can outlive the session it names; send the visitor back to sign in.
  if (!user || !organization) redirect("/login");

  const activeOrganizationId = (await getActiveOrganizationId()) ?? organization.id;
  const roles = user.memberships
    .filter((membership) => membership.organization_id === activeOrganizationId)
    .map((membership) => membership.role);

  return { user, organization, roles };
}

/** Same, but sends anyone without one of `allowed` to their dashboard. */
export async function requireRole(...allowed: Role[]): Promise<SessionContext> {
  const context = await requireSession();
  if (!context.roles.some((role) => allowed.includes(role))) redirect("/dashboard");
  return context;
}
