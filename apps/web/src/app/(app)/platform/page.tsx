import { requirePlatformAdmin } from "@/lib/session-context";

import { PlatformClient } from "./platform-client";

export const metadata = { title: "Businesses · ServiceFlow" };

export default async function PlatformPage() {
  await requirePlatformAdmin();
  return <PlatformClient />;
}
