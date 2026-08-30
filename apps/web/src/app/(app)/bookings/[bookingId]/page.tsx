import { requireRole } from "@/lib/session-context";

import { BookingDetailClient } from "./booking-detail-client";

export const metadata = { title: "Booking · ServiceFlow" };

export default async function BookingDetailPage({
  params,
}: {
  params: Promise<{ bookingId: string }>;
}) {
  const { organization } = await requireRole("ADMIN", "CUSTOMER");
  const { bookingId } = await params;
  return <BookingDetailClient bookingId={bookingId} timeZone={organization.timezone} />;
}
