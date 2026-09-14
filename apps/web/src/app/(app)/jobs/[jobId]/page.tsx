import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { JobDetailClient } from "./job-detail-client";

export const metadata = { title: "Job · ServiceFlow" };

export default async function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { organization, access } = await requirePermission("jobs:read", "jobs:work");
  const { jobId } = await params;
  return (
    <JobDetailClient
      jobId={jobId}
      timeZone={organization.timezone}
      canDispatch={can(access, "jobs:dispatch")}
      canWork={can(access, "jobs:dispatch", "jobs:work")}
      canOpenBooking={can(access, "bookings:read")}
      canReadHistory={can(access, "audit:read")}
      backHref={can(access, "jobs:read") ? "/jobs" : "/schedule"}
    />
  );
}
