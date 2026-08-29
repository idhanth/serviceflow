import { requireRole } from "@/lib/session-context";

import { CustomersClient } from "./customers-client";

export const metadata = { title: "Customers · ServiceFlow" };

export default async function CustomersPage() {
  await requireRole("ADMIN");
  return <CustomersClient />;
}
