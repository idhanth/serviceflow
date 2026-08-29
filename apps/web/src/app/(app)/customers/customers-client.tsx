"use client";

import { MoreHorizontal, Pencil, Plus, Users } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
import { usePagedResource } from "@/hooks/use-resource";
import { formatDate, initialsOf } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Customer } from "@/lib/types";

import { CustomerDetailSheet } from "./customer-detail-sheet";
import { CustomerFormDialog } from "./customer-form-dialog";

const COLUMNS = 5;

export function CustomersClient() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [viewing, setViewing] = useState<Customer | null>(null);

  const params = { q, page, page_size: 10 };
  const query = usePagedResource<Customer>(queryKeys.customers.list(params), "customers", params);

  function search(next: string) {
    setQ(next);
    setPage(1);
  }

  const customers = query.data?.data ?? [];
  const showEmpty = query.isSuccess && customers.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customers"
        description="Everyone you serve, and what they drive."
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden />
            Add customer
          </Button>
        }
      />

      <SearchInput
        value={q}
        onChange={search}
        label="Search customers"
        placeholder="Name, email or phone..."
      />

      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[220px]">Customer</TableHead>
                <TableHead className="min-w-[200px]">Contact</TableHead>
                <TableHead>Vehicles</TableHead>
                <TableHead>Added</TableHead>
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
                      icon={Users}
                      title={q ? "No customers match that search" : "No customers yet"}
                      description={
                        q
                          ? "Try a different name, email or phone number."
                          : "Add your first customer to start booking work for them."
                      }
                      action={
                        q ? (
                          <Button variant="outline" size="sm" onClick={() => search("")}>
                            Clear search
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
                            Add customer
                          </Button>
                        )
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {customers.map((customer) => (
                <TableRow
                  key={customer.id}
                  className="cursor-pointer"
                  onClick={() => setViewing(customer)}
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <Avatar className="size-8">
                        <AvatarFallback className="text-xs">
                          {initialsOf(customer.user.full_name)}
                        </AvatarFallback>
                      </Avatar>
                      <span className="font-medium">{customer.user.full_name}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">{customer.user.email}</div>
                    <div className="text-sm text-muted-foreground">
                      {customer.user.phone ?? "No phone"}
                    </div>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {customer.vehicle_count === 0 ? (
                      <span className="text-muted-foreground">None</span>
                    ) : (
                      customer.vehicle_count
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(customer.created_at)}
                  </TableCell>
                  <TableCell
                    className="text-right"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${customer.user.full_name}`}
                          />
                        }
                      >
                        <MoreHorizontal className="size-4" aria-hidden />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setViewing(customer)}>
                          <Users className="size-4" aria-hidden />
                          View details
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => {
                            setEditing(customer);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="size-4" aria-hidden />
                          Edit
                        </DropdownMenuItem>
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
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="customers" />
      ) : null}

      <CustomerFormDialog open={formOpen} onOpenChange={setFormOpen} customer={editing} />
      <CustomerDetailSheet
        customer={viewing}
        onOpenChange={(open) => !open && setViewing(null)}
      />
    </div>
  );
}
