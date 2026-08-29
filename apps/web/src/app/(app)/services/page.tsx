import { requireRole } from "@/lib/session-context";

import { ServicesClient } from "./services-client";

export const metadata = { title: "Services · ServiceFlow" };

export default async function ServicesPage() {
  await requireRole("ADMIN");
  return <ServicesClient />;
}
