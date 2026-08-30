import { requireRole } from "@/lib/session-context";

import { AdminBookingsClient } from "./admin-bookings-client";
import { CustomerBookingsClient } from "./customer-bookings-client";

export const metadata = { title: "Bookings · ServiceFlow" };

export default async function BookingsPage() {
  const { roles, organization } = await requireRole("ADMIN", "CUSTOMER");
  // Times are displayed in the shop's timezone, not the browser's (PRD 40).
  return roles.includes("ADMIN") ? (
    <AdminBookingsClient timeZone={organization.timezone} />
  ) : (
    <CustomerBookingsClient timeZone={organization.timezone} />
  );
}
