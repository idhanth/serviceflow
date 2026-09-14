import { CalendarPlus } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/data/page-header";
import { Button } from "@/components/ui/button";
import { can, homePathFor } from "@/lib/permissions";
import { requireTenantSession } from "@/lib/session-context";

import { OperationsDashboard } from "./operations-dashboard";

export const metadata = { title: "Dashboard · ServiceFlow" };

export default async function DashboardPage() {
  const { organization, access } = await requireTenantSession();
  // Technicians start on their schedule and customers on their bookings: each
  // role opens on the thing it is responsible for.
  if (!can(access, "dashboard:read")) redirect(homePathFor(access));

  const dateLabel = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: organization.timezone,
  }).format(new Date());

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        meta={<span className="text-[13px] text-muted-foreground">{dateLabel}</span>}
        description={`What's happening at ${organization.name} today, and what needs someone.`}
        action={
          can(access, "bookings:write") ? (
            <Button size="sm" render={<Link href="/bookings/new" />}>
              <CalendarPlus className="size-3.5" aria-hidden />
              New booking
            </Button>
          ) : null
        }
      />
      <OperationsDashboard
        timeZone={organization.timezone}
        canDispatch={can(access, "jobs:dispatch")}
      />
    </div>
  );
}
