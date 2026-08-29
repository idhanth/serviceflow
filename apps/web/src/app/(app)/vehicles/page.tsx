import { requireRole } from "@/lib/session-context";

import { AdminVehiclesClient } from "./admin-vehicles-client";
import { MyGarageClient } from "./my-garage-client";

export const metadata = { title: "Vehicles · ServiceFlow" };

export default async function VehiclesPage() {
  const { roles } = await requireRole("ADMIN", "CUSTOMER");
  // Admins get the org-wide table; everyone else sees only their own garage.
  return roles.includes("ADMIN") ? <AdminVehiclesClient /> : <MyGarageClient />;
}
