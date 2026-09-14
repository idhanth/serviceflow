import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { BookingDetailClient } from "./booking-detail-client";

export const metadata = { title: "Booking · ServiceFlow" };

export default async function BookingDetailPage({ params }: { params: Promise<{ bookingId: string }> }) {
  const { organization, access } = await requirePermission("bookings:read", "bookings:own");
  const { bookingId } = await params;
  return (
    <BookingDetailClient
      bookingId={bookingId}
      timeZone={organization.timezone}
      staff={can(access, "bookings:read")}
      canOpenJob={can(access, "jobs:read")}
    />
  );
}
