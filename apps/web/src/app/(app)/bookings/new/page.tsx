import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { BookingWizard } from "./booking-wizard";

export const metadata = { title: "New booking · ServiceFlow" };

export default async function NewBookingPage({
  searchParams,
}: {
  searchParams: Promise<{ customer_id?: string }>;
}) {
  const { organization, access } = await requirePermission("bookings:write", "bookings:own");
  const { customer_id: customerId } = await searchParams;
  return (
    <BookingWizard
      timeZone={organization.timezone}
      staff={can(access, "bookings:write")}
      initialCustomerId={customerId ?? null}
    />
  );
}
