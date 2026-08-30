"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePagedResource } from "@/hooks/use-resource";
import { apiFetch, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Availability, Employee } from "@/lib/types";

import { OverridesPanel } from "./overrides-panel";
import { WeeklyEditor } from "./weekly-editor";

function Loading() {
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-5">
        <Skeleton className="h-5 w-40" />
        {[0, 1, 2, 3, 4].map((row) => (
          <Skeleton key={row} className="h-9 w-full" />
        ))}
      </Card>
    </div>
  );
}

/** Admins pick whose availability to manage; employees only ever see their own. */
function EmployeePicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (id: string) => void;
}) {
  const params = { active: true, page_size: 100 };
  const employees = usePagedResource<Employee>(
    queryKeys.employees.list(params),
    "employees",
    params,
  );

  if (employees.isPending) return <Skeleton className="h-10 w-full sm:max-w-xs" />;
  if (employees.isError) {
    return <ErrorState error={employees.error} onRetry={() => employees.refetch()} />;
  }

  const rows = employees.data?.data ?? [];
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={CalendarClock}
          title="No active employees"
          description="Add someone to the team before setting working hours."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-1.5">
      <label htmlFor="who" className="text-sm font-medium">
        Employee
      </label>
      <select
        id="who"
        className="h-10 w-full rounded-lg border bg-background px-3 text-sm sm:max-w-xs"
        value={value ?? rows[0].id}
        onChange={(event) => onChange(event.target.value)}
      >
        {rows.map((employee) => (
          <option key={employee.id} value={employee.id}>
            {employee.user.full_name} — {employee.job_title}
          </option>
        ))}
      </select>
    </div>
  );
}

export function AvailabilityClient({
  isAdmin,
  ownEmployeeId,
}: {
  isAdmin: boolean;
  ownEmployeeId: string | null;
}) {
  const [selected, setSelected] = useState<string | null>(ownEmployeeId);
  const employeeId = isAdmin ? selected : ownEmployeeId;

  const query = useQuery<{ data: Availability }, ApiError>({
    queryKey: queryKeys.availability.detail(employeeId ?? "none"),
    queryFn: () => apiFetch<{ data: Availability }>(`employees/${employeeId}/availability`),
    enabled: Boolean(employeeId),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Availability"
        description={
          isAdmin
            ? "Working hours and time off for your team. This decides who can be assigned when."
            : "Your working hours and time off. Admins assign work inside these."
        }
      />

      {isAdmin ? <EmployeePicker value={selected} onChange={setSelected} /> : null}

      {!employeeId && !isAdmin ? (
        <Card>
          <EmptyState
            icon={CalendarClock}
            title="No employee profile"
            description="Your account isn't linked to an employee record, so there's no schedule to manage."
          />
        </Card>
      ) : null}

      {employeeId && query.isPending ? <Loading /> : null}

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : null}

      {query.data ? (
        <div className="space-y-4">
          <WeeklyEditor availability={query.data.data} canEdit />
          <OverridesPanel availability={query.data.data} canEdit />
        </div>
      ) : null}
    </div>
  );
}
