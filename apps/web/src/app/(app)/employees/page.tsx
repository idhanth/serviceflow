import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { EmployeesClient } from "./employees-client";

export const metadata = { title: "Employees · ServiceFlow" };

export default async function EmployeesPage() {
  const { access } = await requirePermission("employees:write", "services:read_retired");
  return <EmployeesClient canWrite={can(access, "employees:write")} />;
}
