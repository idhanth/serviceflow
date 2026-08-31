import { requireRole } from "@/lib/session-context";

import { ActivityClient } from "./activity-client";

export const metadata = { title: "Activity · ServiceFlow" };

export default async function ActivityPage() {
  const { organization } = await requireRole("ADMIN");
  return <ActivityClient timeZone={organization.timezone} />;
}
