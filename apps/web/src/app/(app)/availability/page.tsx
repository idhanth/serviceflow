import { requireRole } from "@/lib/session-context";
import { serverFetchData } from "@/lib/server-api";
import type { Employee } from "@/lib/types";

import { AvailabilityClient } from "./availability-client";

export const metadata = { title: "Availability · ServiceFlow" };

export default async function AvailabilityPage() {
  const { roles } = await requireRole("ADMIN", "EMPLOYEE");
  const isAdmin = roles.includes("ADMIN");

  // An admin may also be an employee; either way we only need their own id when
  // they are not an admin, and a missing profile is handled in the client.
  const own = isAdmin ? null : await serverFetchData<Employee>("employees/me");

  return <AvailabilityClient isAdmin={isAdmin} ownEmployeeId={own?.id ?? null} />;
}
