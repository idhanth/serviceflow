import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";
import { serverFetchData } from "@/lib/server-api";
import type { Employee } from "@/lib/types";

import { AvailabilityClient } from "./availability-client";

export const metadata = { title: "Availability · ServiceFlow" };

export default async function AvailabilityPage() {
  const { access } = await requirePermission("availability:manage", "availability:own");
  const manager = can(access, "availability:manage");

  // A technician edits their own hours; anyone who manages the team picks whose.
  const own = manager ? null : await serverFetchData<Employee>("employees/me");

  return <AvailabilityClient isAdmin={manager} ownEmployeeId={own?.id ?? null} />;
}
