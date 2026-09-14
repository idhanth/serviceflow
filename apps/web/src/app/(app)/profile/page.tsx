import { requirePermission } from "@/lib/session-context";

import { ProfileClient } from "./profile-client";

export const metadata = { title: "Profile · ServiceFlow" };

export default async function ProfilePage() {
  const { organization } = await requirePermission("bookings:own");
  return <ProfileClient businessName={organization.name} />;
}
