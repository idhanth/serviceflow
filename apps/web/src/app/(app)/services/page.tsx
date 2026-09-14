import { can } from "@/lib/permissions";
import { requirePermission } from "@/lib/session-context";

import { ServicesClient } from "./services-client";

export const metadata = { title: "Services · ServiceFlow" };

export default async function ServicesPage() {
  const { access } = await requirePermission("services:write", "services:read_retired");
  return <ServicesClient canWrite={can(access, "services:write")} />;
}
