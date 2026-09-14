import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { SettingsClient } from "./settings-client";

export const metadata = { title: "Settings · ServiceFlow" };

export default async function SettingsPage() {
  const { organization, access, user } = await requirePermission("members:read", "organization:manage");
  return (
    <SettingsClient
      organization={organization}
      currentUserId={user.id}
      canManageBusiness={can(access, "organization:manage")}
      canManageMembers={can(access, "members:manage")}
    />
  );
}
