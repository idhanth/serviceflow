import { redirect } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getActiveOrganizationId } from "@/lib/session";
import { serverFetchData } from "@/lib/server-api";
import type { Organization, SessionUser } from "@/lib/types";

function greeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default async function DashboardPage() {
  const [user, organization] = await Promise.all([
    serverFetchData<SessionUser>("auth/me"),
    serverFetchData<Organization>("organizations/current"),
  ]);
  if (!user || !organization) redirect("/login");

  const activeOrganizationId = (await getActiveOrganizationId()) ?? organization.id;
  const roles = user.memberships
    .filter((m) => m.organization_id === activeOrganizationId)
    .map((m) => m.role);

  const now = new Date();
  const dateLabel = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: organization.timezone,
  }).format(now);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          {greeting(now)}, {user.first_name}
        </h1>
        <p className="text-sm text-muted-foreground">{dateLabel}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Foundation is live</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <p className="text-muted-foreground">
            Authentication, per-organization roles and tenant-scoped API access are
            working. Bookings, scheduling and jobs land in the next phases.
          </p>
          <dl className="grid gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                Organization
              </dt>
              <dd className="mt-1 font-medium">{organization.name}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Timezone</dt>
              <dd className="mt-1 font-medium">{organization.timezone}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                Your access
              </dt>
              <dd className="mt-1 flex flex-wrap gap-1.5">
                {roles.map((role) => (
                  <Badge key={role} variant="secondary">
                    {role.toLowerCase()}
                  </Badge>
                ))}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
