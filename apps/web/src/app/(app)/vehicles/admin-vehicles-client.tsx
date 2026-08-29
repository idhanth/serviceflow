"use client";

import { Car, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
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
import { VehicleFormDialog } from "@/components/vehicles/vehicle-form-dialog";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetch } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Vehicle } from "@/lib/types";

const COLUMNS = 5;

export function AdminVehiclesClient() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Vehicle | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [removing, setRemoving] = useState<Vehicle | null>(null);

  const params = { q, page, page_size: 12 };
  const query = usePagedResource<Vehicle>(queryKeys.vehicles.list(params), "vehicles", params);

  const removeVehicle = useResourceMutation<Vehicle, null>(
    async (vehicle) => {
      await apiFetch(`vehicles/${vehicle.id}`, { method: "DELETE" });
      return null;
    },
    {
      invalidate: [queryKeys.vehicles.all, queryKeys.customers.all],
      successMessage: "Vehicle removed",
    },
  );

  function search(next: string) {
    setQ(next);
    setPage(1);
  }

  const vehicles = query.data?.data ?? [];
  const showEmpty = query.isSuccess && vehicles.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Vehicles"
        description="Every vehicle on your books, across all customers."
      />

      <SearchInput
        value={q}
        onChange={search}
        label="Search vehicles"
        placeholder="Make, model, colour or plate..."
      />

      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[200px]">Vehicle</TableHead>
                <TableHead className="min-w-[160px]">Owner</TableHead>
                <TableHead>Plate</TableHead>
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
                      icon={Car}
                      title={q ? "No vehicles match that search" : "No vehicles yet"}
                      description={
                        q
                          ? "Try a different make, model or plate."
                          : "Vehicles are added from a customer's profile on the Customers page."
                      }
                      action={
                        q ? (
                          <Button variant="outline" size="sm" onClick={() => search("")}>
                            Clear search
                          </Button>
                        ) : null
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {vehicles.map((vehicle) => (
                <TableRow key={vehicle.id}>
                  <TableCell>
                    <div className="font-medium">{vehicle.display_name}</div>
                    <div className="text-sm text-muted-foreground">
                      {vehicle.color ?? "Colour not recorded"}
                    </div>
                  </TableCell>
                  <TableCell>{vehicle.owner?.full_name ?? "—"}</TableCell>
                  <TableCell className="font-mono text-sm">
                    {vehicle.license_plate ?? <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(vehicle.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${vehicle.display_name}`}
                          />
                        }
                      >
                        <MoreHorizontal className="size-4" aria-hidden />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => {
                            setEditing(vehicle);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="size-4" aria-hidden />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => setRemoving(vehicle)}
                        >
                          <Trash2 className="size-4" aria-hidden />
                          Remove
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
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="vehicles" />
      ) : null}

      <VehicleFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        vehicle={editing}
        ownerName={editing?.owner?.full_name}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.display_name ?? "this vehicle"}?`}
        description={`This deletes the vehicle from ${removing?.owner?.full_name ?? "the customer"}'s account. This cannot be undone.`}
        confirmLabel="Remove vehicle"
        pendingLabel="Removing..."
        onConfirm={async () => {
          if (removing) await removeVehicle.mutateAsync(removing);
        }}
      />
    </div>
  );
}
