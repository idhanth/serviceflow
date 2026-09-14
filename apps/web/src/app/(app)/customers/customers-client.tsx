"use client";

import { CalendarPlus, MoreHorizontal, Pencil, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { MobileList, MobileRow } from "@/components/data/mobile-list";
import { PageHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { Segmented } from "@/components/data/segmented";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePagedResource } from "@/hooks/use-resource";
import { formatDate, formatRelative } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Customer } from "@/lib/types";

import { CustomerFormDialog } from "./customer-form-dialog";

const SORTS = [
  { label: "A–Z", value: "name" },
  { label: "Newest", value: "-created_at" },
] as const;

type Sort = (typeof SORTS)[number]["value"];

/**
 * The customer list: who, where, and how much work they've had.
 *
 * Search, sort and pagination run on the server, so the list stays fast at
 * ten thousand customers. The address is on every row because in field service
 * it is how people are told apart.
 */
export function CustomersClient({
  canWrite,
  canBook,
  startAdding,
  initialSort,
}: {
  canWrite: boolean;
  canBook: boolean;
  startAdding: boolean;
  initialSort: Sort;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>(initialSort);
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(startAdding && canWrite);
  const [editing, setEditing] = useState<Customer | null>(null);

  const params = { q, sort, page, page_size: 20 };
  const query = usePagedResource<Customer>(queryKeys.customers.list(params), "customers", params);
  const customers = query.data?.data ?? [];
  const columns = 5;
  const open = (id: string) => router.push(`/customers/${id}`);

  function add() {
    setEditing(null);
    setFormOpen(true);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Customers"
        description="Everyone the business serves, where the work happens, and their history."
        meta={
          query.data ? (
            <span className="text-[13px] text-muted-foreground tabular-nums">{query.data.meta.total.toLocaleString()} total</span>
          ) : null
        }
        action={
          canWrite ? (
            <Button size="sm" onClick={add}>
              <Plus className="size-3.5" aria-hidden />
              Add customer
            </Button>
          ) : null
        }
      />

      <Toolbar className="justify-between">
        <SearchInput
          value={q}
          onChange={(next) => {
            setQ(next);
            setPage(1);
          }}
          label="Search customers"
          placeholder="Name, email, phone or address"
        />
        <Segmented
          label="Sort customers"
          value={sort}
          onChange={(next) => {
            setSort(next);
            setPage(1);
          }}
          options={SORTS}
        />
      </Toolbar>

      <DataPanel>
        <MobileList>
          {customers.map((customer) => (
            <MobileRow
              key={customer.id}
              onClick={() => open(customer.id)}
              title={customer.user.full_name}
              subtitle={customer.address ?? customer.user.email}
              trailing={<span className="text-[12px] text-muted-foreground tabular-nums">{customer.booking_count} bookings</span>}
            />
          ))}
        </MobileList>

        <div className="hidden overflow-x-auto md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[240px]">Customer</TableHead>
                <TableHead className="min-w-[200px]">Contact</TableHead>
                <TableHead className="min-w-[120px] text-right">Bookings</TableHead>
                <TableHead className="min-w-[130px]">Last service</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={columns} /> : null}

              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}

              {query.isSuccess && customers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={columns} className="p-0">
                    <EmptyState
                      icon={Users}
                      title={q ? `No customers match “${q}”` : "No customers yet"}
                      description={
                        q ? "Try a different name, email, phone number or street." : "Add your first customer to start booking work for them."
                      }
                      action={
                        q ? (
                          <Button variant="outline" size="sm" onClick={() => setQ("")}>
                            Clear search
                          </Button>
                        ) : canWrite ? (
                          <Button size="sm" onClick={add}>
                            <Plus className="size-3.5" aria-hidden />
                            Add customer
                          </Button>
                        ) : null
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {customers.map((customer) => (
                <TableRow
                  key={customer.id}
                  tabIndex={0}
                  aria-label={`Open ${customer.user.full_name}`}
                  className="cursor-pointer"
                  onClick={() => open(customer.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      open(customer.id);
                    }
                  }}
                >
                  <TableCell>
                    <PrimaryCell
                      title={
                        <Link
                          href={`/customers/${customer.id}`}
                          className="focus-ring hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {customer.user.full_name}
                        </Link>
                      }
                      subtitle={customer.address ?? "No address on file"}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="truncate text-[13px]">{customer.user.email}</div>
                    <div className="text-[12px] text-muted-foreground">{customer.user.phone ?? "No phone"}</div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {customer.booking_count === 0 ? <span className="text-muted-foreground">None</span> : customer.booking_count}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {customer.last_service_at ? formatRelative(customer.last_service_at) : `Added ${formatDate(customer.created_at)}`}
                  </TableCell>
                  <TableCell className="text-right" onClick={(event) => event.stopPropagation()}>
                    {canWrite || canBook ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={<Button variant="ghost" size="icon" aria-label={`Actions for ${customer.user.full_name}`} />}
                        >
                          <MoreHorizontal className="size-4" aria-hidden />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {canBook ? (
                            <DropdownMenuItem onClick={() => router.push(`/bookings/new?customer_id=${customer.id}`)}>
                              <CalendarPlus className="size-4" aria-hidden />
                              New booking
                            </DropdownMenuItem>
                          ) : null}
                          {canWrite ? (
                            <DropdownMenuItem
                              onClick={() => {
                                setEditing(customer);
                                setFormOpen(true);
                              }}
                            >
                              <Pencil className="size-4" aria-hidden />
                              Edit
                            </DropdownMenuItem>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {query.data && query.data.meta.total > 0 ? (
          <PanelFooter>
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="customers" />
          </PanelFooter>
        ) : null}
      </DataPanel>

      {canWrite ? <CustomerFormDialog open={formOpen} onOpenChange={setFormOpen} customer={editing} /> : null}
    </div>
  );
}
