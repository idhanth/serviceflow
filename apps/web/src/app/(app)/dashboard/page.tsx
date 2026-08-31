import { CalendarPlus } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { requireSession } from "@/lib/session-context";

import { AdminOverview } from "./admin-overview";
import { CustomerOverview } from "./customer-overview";
import { EmployeeOverview } from "./employee-overview";

export const metadata = { title: "Overview · ServiceFlow" };

export default async function DashboardPage() {
  const { organization, roles } = await requireSession();

  const dateLabel = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: organization.timezone,
  }).format(new Date());

  // Each role opens on the thing it is responsible for. The header is the same
  // shape everywhere: what this is, and today's date for context.
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">
            {roles.includes("ADMIN")
              ? organization.name
              : roles.includes("EMPLOYEE")
                ? "My work"
                : "Your appointments"}
          </h1>
          <p className="text-[13px] text-muted-foreground">{dateLabel}</p>
        </div>

        {/* A customer's one action belongs with the page title, not buried
            beside a section heading further down. */}
        {roles.includes("CUSTOMER") && !roles.includes("ADMIN") ? (
          <Button size="sm" render={<Link href="/bookings/new" />}>
            <CalendarPlus className="size-3.5" aria-hidden />
            Book a service
          </Button>
        ) : null}
      </header>

      {roles.includes("ADMIN") ? (
        <AdminOverview timeZone={organization.timezone} />
      ) : roles.includes("EMPLOYEE") ? (
        <EmployeeOverview timeZone={organization.timezone} />
      ) : (
        <CustomerOverview timeZone={organization.timezone} />
      )}
    </div>
  );
}
