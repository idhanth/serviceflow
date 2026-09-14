import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { AdminBookingsClient } from "./admin-bookings-client";
import { CustomerBookingsClient } from "./customer-bookings-client";

export const metadata = { title: "Bookings · ServiceFlow" };

export default async function BookingsPage() {
  const { organization, access } = await requirePermission("bookings:read", "bookings:own");
  // Times are displayed in the business's timezone, not the browser's.
  return can(access, "bookings:read") ? (
    <AdminBookingsClient
      timeZone={organization.timezone}
      canWrite={can(access, "bookings:write")}
      canOpenCustomers={can(access, "customers:read")}
    />
  ) : (
    <CustomerBookingsClient timeZone={organization.timezone} />
  );
}
