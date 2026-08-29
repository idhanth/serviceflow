"use client";

import { MoreHorizontal, Pencil, Plus, UserMinus, UserSquare, UserCheck } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { ActiveBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          value={q}
          onChange={search}
          label="Search employees"
          placeholder="Name, email or job title..."
        />
        <div
          role="group"
          aria-label="Filter by status"
          className="flex rounded-lg border p-0.5"
        >
          {FILTERS.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={filter === option.value ? "secondary" : "ghost"}
              aria-pressed={filter === option.value}
              onClick={() => changeFilter(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[220px]">Employee</TableHead>
                <TableHead className="min-w-[180px]">Contact</TableHead>
                <TableHead className="min-w-[220px]">Qualified for</TableHead>
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
                    <div className="flex items-center gap-3">
                      <Avatar className="size-8">
                        <AvatarFallback className="text-xs">
                          {initialsOf(employee.user.full_name)}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="truncate font-medium">{employee.user.full_name}</div>
                        <div className="truncate text-sm text-muted-foreground">
                          {employee.job_title}
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">{employee.user.email}</div>
                    <div className="text-sm text-muted-foreground">
                      {employee.user.phone ?? "No phone"}
                    </div>
                  </TableCell>
                  <TableCell>
                    {employee.services.length === 0 ? (
                      <span className="text-sm text-muted-foreground">
                        No services assigned
                      </span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {employee.services.slice(0, 3).map((service) => (
                          <Badge key={service.id} variant="secondary" className="font-normal">
                            {service.name}
                          </Badge>
                        ))}
                        {employee.services.length > 3 ? (
                          <Badge variant="outline" className="font-normal">
                            +{employee.services.length - 3}
                          </Badge>
                        ) : null}
                      </div>
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
      </Card>

      {query.data ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="employees" />
      ) : null}

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
