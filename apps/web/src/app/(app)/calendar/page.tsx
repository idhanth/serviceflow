import { requireRole } from "@/lib/session-context";

import { CalendarClient } from "./calendar-client";

export const metadata = { title: "Calendar · ServiceFlow" };

export default async function CalendarPage() {
  const { roles, organization } = await requireRole("ADMIN", "EMPLOYEE");
  return (
    <CalendarClient timeZone={organization.timezone} isAdmin={roles.includes("ADMIN")} />
  );
}
