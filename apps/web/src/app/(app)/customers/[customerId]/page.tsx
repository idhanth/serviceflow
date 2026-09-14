import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { CustomerDetailClient } from "./customer-detail-client";

export const metadata = { title: "Customer · ServiceFlow" };

export default async function CustomerDetailPage({ params }: { params: Promise<{ customerId: string }> }) {
  const { organization, access } = await requirePermission("customers:read");
  const { customerId } = await params;
  return (
    <CustomerDetailClient
      customerId={customerId}
      timeZone={organization.timezone}
      canWrite={can(access, "customers:write")}
      canArchive={can(access, "customers:archive")}
      canBook={can(access, "bookings:write")}
      canOpenJobs={can(access, "jobs:read")}
    />
  );
}
