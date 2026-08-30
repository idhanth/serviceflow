import { requireRole } from "@/lib/session-context";

import { JobDetailClient } from "./job-detail-client";

export const metadata = { title: "Job · ServiceFlow" };

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { organization } = await requireRole("ADMIN", "EMPLOYEE");
  const { jobId } = await params;
  return <JobDetailClient jobId={jobId} timeZone={organization.timezone} />;
}
