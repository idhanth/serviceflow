import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/app-shell";
import { getActiveOrganizationId } from "@/lib/session";
import { serverFetchData } from "@/lib/server-api";
import type { Organization, SessionUser } from "@/lib/types";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [user, organization] = await Promise.all([
    serverFetchData<SessionUser>("auth/me"),
    serverFetchData<Organization>("organizations/current"),
  ]);

  // A cookie can outlive the session it names; send the visitor back to sign in.
  if (!user || !organization) redirect("/login");

  const activeOrganizationId = (await getActiveOrganizationId()) ?? organization.id;
  const roles = user.memberships
    .filter((m) => m.organization_id === activeOrganizationId)
    .map((m) => m.role);

  return (
    <AppShell user={user} organization={organization} roles={roles}>
      {children}
    </AppShell>
  );
}
