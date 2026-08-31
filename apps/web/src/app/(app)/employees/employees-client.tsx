"use client";

import { MoreHorizontal, Pencil, Plus, UserMinus, UserSquare, UserCheck } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { Segmented } from "@/components/data/segmented";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { ActiveBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { initialsOf } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Employee } from "@/lib/types";

import { EmployeeFormDialog } from "./employee-form-dialog";

const COLUMNS = 5;
const FILTERS = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Inactive", value: "inactive" },
] as const;

type Filter = (typeof FILTERS)[number]["value"];

export function EmployeesClient() {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [deactivating, setDeactivating] = useState<Employee | null>(null);

  const params = {
    q,
    page,
    page_size: 10,
    active: filter === "all" ? undefined : filter === "active",
  };
  const query = usePagedResource<Employee>(queryKeys.employees.list(params), "employees", params);

  const setActive = useResourceMutation<{ employee: Employee; active: boolean }, Employee>(
    ({ employee, active }) =>
      apiFetchData<Employee>(`employees/${employee.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active }),
      }),
    {
      invalidate: [queryKeys.employees.all],
      successMessage: (result) =>
        result.active
          ? `${result.user.full_name} reactivated`
          : `${result.user.full_name} deactivated`,
    },
  );

  function search(next: string) {
    setQ(next);
    setPage(1);
  }

  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(1);
  }

  const employees = query.data?.data ?? [];
  const showEmpty = query.isSuccess && employees.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        description="Your team and what each person is qualified to do."
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden />
            Add employee
          </Button>
        }
      />

      <Toolbar>
        <Segmented
          label="Filter by status"
          value={filter}
          onChange={changeFilter}
          options={FILTERS}
        />
        <SearchInput
          value={q}
          onChange={search}
          label="Search employees"
          placeholder="Search team"
        />
      </Toolbar>

      <DataPanel>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[240px]">Employee</TableHead>
                <TableHead className="min-w-[220px]">Contact</TableHead>
                <TableHead className="min-w-[260px]">Qualified for</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-12 sr-only">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={COLUMNS} /> : null}

              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}

              {showEmpty ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <EmptyState
                      icon={UserSquare}
                      title={
                        q || filter !== "all" ? "Nobody matches these filters" : "No employees yet"
                      }
                      description={
                        q || filter !== "all"
                          ? "Try a different search, or switch the status filter."
                          : "Add your team so bookings can be assigned to them."
                      }
                      action={
                        q || filter !== "all" ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              search("");
                              changeFilter("all");
                            }}
                          >
                            Clear filters
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            onClick={() => {
                              setEditing(null);
                              setFormOpen(true);
                            }}
                          >
                            <Plus className="size-4" aria-hidden />
                            Add employee
                          </Button>
                        )
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {employees.map((employee) => (
                <TableRow key={employee.id} className={employee.active ? undefined : "opacity-70"}>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <Avatar className="size-7">
                        <AvatarFallback className="text-[11px]">
                          {initialsOf(employee.user.full_name)}
                        </AvatarFallback>
                      </Avatar>
                      <PrimaryCell
                        title={employee.user.full_name}
                        subtitle={employee.job_title}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <PrimaryCell
                      title={<span className="font-normal">{employee.user.email}</span>}
                      subtitle={employee.user.phone ?? "—"}
                    />
                  </TableCell>
                  <TableCell>
                    {/* Qualifications are reference detail, not the point of the
                        row: a quiet list reads faster than eight pills. */}
                    {employee.services.length === 0 ? (
                      <span className="text-muted-foreground">No services assigned</span>
                    ) : (
                      <span className="text-muted-foreground">
                        <span className="text-foreground">
                          {employee.services
                            .slice(0, 2)
                            .map((service) => service.name)
                            .join(", ")}
                        </span>
                        {employee.services.length > 2
                          ? ` +${employee.services.length - 2} more`
                          : ""}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <ActiveBadge active={employee.active} />
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${employee.user.full_name}`}
                          />
                        }
                      >
                        <MoreHorizontal className="size-4" aria-hidden />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => {
                            setEditing(employee);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="size-4" aria-hidden />
                          Edit
                        </DropdownMenuItem>
                        {employee.active ? (
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setDeactivating(employee)}
                          >
                            <UserMinus className="size-4" aria-hidden />
                            Deactivate
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem
                            onClick={() => setActive.mutate({ employee, active: true })}
                          >
                            <UserCheck className="size-4" aria-hidden />
                            Reactivate
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="employees" />
          </PanelFooter>
        ) : null}
      </DataPanel>

      <EmployeeFormDialog open={formOpen} onOpenChange={setFormOpen} employee={editing} />

      <ConfirmDialog
        open={deactivating !== null}
        onOpenChange={(open) => !open && setDeactivating(null)}
        title={`Deactivate ${deactivating?.user.full_name ?? "this employee"}?`}
        description="They immediately lose access to ServiceFlow and stop appearing for new assignments. Their past work is kept, and you can reactivate them later."
        confirmLabel="Deactivate"
        pendingLabel="Deactivating..."
        onConfirm={async () => {
          if (deactivating) await setActive.mutateAsync({ employee: deactivating, active: false });
        }}
      />
    </div>
  );
}
