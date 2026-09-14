import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { JobsClient } from "./jobs-client";

export const metadata = { title: "Jobs · ServiceFlow" };

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { organization, access } = await requirePermission("jobs:read", "jobs:work");
  const { status } = await searchParams;
  return (
    <JobsClient
      timeZone={organization.timezone}
      team={can(access, "jobs:read")}
      initialFilter={status}
    />
  );
}
