import { requireRole } from "@/lib/session-context";

import { JobsClient } from "./jobs-client";

export const metadata = { title: "Jobs · ServiceFlow" };

export default async function JobsPage() {
  const { roles, organization } = await requireRole("ADMIN", "EMPLOYEE");
  return <JobsClient timeZone={organization.timezone} isAdmin={roles.includes("ADMIN")} />;
}
