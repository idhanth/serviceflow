import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { ScheduleClient } from "./schedule-client";

export const metadata = { title: "Schedule · ServiceFlow" };

export default async function SchedulePage() {
  const { organization, access } = await requirePermission("schedule:read", "schedule:own");
  return (
    <ScheduleClient
      timeZone={organization.timezone}
      team={can(access, "schedule:read")}
      canBook={can(access, "bookings:write")}
    />
  );
}
