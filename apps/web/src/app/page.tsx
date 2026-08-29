import { redirect } from "next/navigation";

import { getSessionToken } from "@/lib/session";

export default async function RootPage() {
  redirect((await getSessionToken()) ? "/dashboard" : "/login");
}
