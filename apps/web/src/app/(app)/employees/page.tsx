import { requireRole } from "@/lib/session-context";

import { EmployeesClient } from "./employees-client";

export const metadata = { title: "Employees · ServiceFlow" };

export default async function EmployeesPage() {
  await requireRole("ADMIN");
  return <EmployeesClient />;
}
