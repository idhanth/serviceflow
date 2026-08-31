"use client";

import { MoreHorizontal, Pencil, Plus, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { DataPanel, PanelFooter } from "@/components/data/data-panel";
import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { ActiveBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
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
import { formatDuration, formatPrice } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Service } from "@/lib/types";

import { ServiceFormDialog } from "./service-form-dialog";

const COLUMNS = 6;

export function ServicesClient() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Service | null>(null);
  const [retiring, setRetiring] = useState<Service | null>(null);

  const params = { q, page, page_size: 10 };
  const query = usePagedResource<Service>(queryKeys.services.list(params), "services", params);

  const setActive = useResourceMutation<{ service: Service; active: boolean }, Service>(
    ({ service, active }) =>
      active
        ? apiFetchData<Service>(`services/${service.id}`, {
            method: "PATCH",
            body: JSON.stringify({ active: true }),
          })
        : apiFetchData<Service>(`services/${service.id}`, { method: "DELETE" }),
    {
      invalidate: [queryKeys.services.all],
      successMessage: (result) => (result.active ? `${result.name} restored` : `${result.name} retired`),
    },
  );

  function search(next: string) {
    setQ(next);
    setPage(1);
  }

  const services = query.data?.data ?? [];
  const showEmpty = query.isSuccess && services.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Services"
        description="What you offer, what it costs, and how long it takes."
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden />
            Add service
          </Button>
        }
      />

      <SearchInput
        value={q}
        onChange={search}
        label="Search services"
        placeholder="Search services"
      />

      <DataPanel>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[200px]">Service</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Qualified staff</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-12 text-right sr-only">Actions</TableHead>
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
                      icon={Sparkles}
                      title={q ? "No services match that search" : "No services yet"}
                      description={
                        q
                          ? "Try a different name, or clear the search to see everything."
                          : "Add the packages you offer so customers have something to book."
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
                            Add service
                          </Button>
                        )
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {services.map((service) => (
                <TableRow key={service.id} className={service.active ? undefined : "opacity-70"}>
                  <TableCell>
                    <div className="font-medium">{service.name}</div>
                    {service.description ? (
                      <div className="line-clamp-1 max-w-lg text-[12px] text-muted-foreground">
                        {service.description}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatPrice(service.base_price)}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {formatDuration(service.duration_minutes)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {service.employee_count === 0
                      ? "Nobody yet"
                      : `${service.employee_count} ${service.employee_count === 1 ? "person" : "people"}`}
                  </TableCell>
                  <TableCell>
                    <ActiveBadge active={service.active} inactiveLabel="Retired" />
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${service.name}`}
                          />
                        }
                      >
                        <MoreHorizontal className="size-4" aria-hidden />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => {
                            setEditing(service);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="size-4" aria-hidden />
                          Edit
                        </DropdownMenuItem>
                        {service.active ? (
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setRetiring(service)}
                          >
                            <Trash2 className="size-4" aria-hidden />
                            Retire
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem
                            onClick={() => setActive.mutate({ service, active: true })}
                          >
                            <RotateCcw className="size-4" aria-hidden />
                            Restore
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
            <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="services" />
          </PanelFooter>
        ) : null}
      </DataPanel>

      <ServiceFormDialog open={formOpen} onOpenChange={setFormOpen} service={editing} />

      <ConfirmDialog
        open={retiring !== null}
        onOpenChange={(open) => !open && setRetiring(null)}
        title={`Retire ${retiring?.name ?? "this service"}?`}
        description="It stops appearing for new bookings. Existing jobs and history keep it, and you can restore it at any time."
        confirmLabel="Retire service"
        pendingLabel="Retiring..."
        onConfirm={async () => {
          if (retiring) await setActive.mutateAsync({ service: retiring, active: false });
        }}
      />
    </div>
  );
}
