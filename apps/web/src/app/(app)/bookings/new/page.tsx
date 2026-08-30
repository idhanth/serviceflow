import { requireRole } from "@/lib/session-context";

import { BookingWizard } from "./booking-wizard";

export const metadata = { title: "Book a service · ServiceFlow" };

export default async function NewBookingPage() {
  await requireRole("CUSTOMER");
  return <BookingWizard />;
}
