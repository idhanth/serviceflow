import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { CustomersClient } from "./customers-client";

export const metadata = { title: "Customers · ServiceFlow" };

export default async function CustomersPage({
  searchParams,
}: {
  searchParams: Promise<{ new?: string; sort?: string }>;
}) {
  const { access } = await requirePermission("customers:read");
  const { new: startAdding, sort } = await searchParams;
  return (
    <CustomersClient
      canWrite={can(access, "customers:write")}
      canBook={can(access, "bookings:write")}
      startAdding={startAdding === "1"}
      initialSort={sort === "-created_at" ? "-created_at" : "name"}
    />
  );
}
