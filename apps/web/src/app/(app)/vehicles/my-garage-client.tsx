"use client";

import { Car, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { PageHeader } from "@/components/data/page-header";
import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { VehicleFormDialog } from "@/components/vehicles/vehicle-form-dialog";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetch } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Vehicle } from "@/lib/types";

/** A customer's own vehicles. The API scopes this to them; no owner filter exists here. */
export function MyGarageClient() {
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Vehicle | null>(null);
  const [removing, setRemoving] = useState<Vehicle | null>(null);

  const params = { page_size: 50 };
  const query = usePagedResource<Vehicle>(queryKeys.vehicles.list(params), "vehicles", params);

  const removeVehicle = useResourceMutation<Vehicle, null>(
    async (vehicle) => {
      await apiFetch(`vehicles/${vehicle.id}`, { method: "DELETE" });
      return null;
    },
    { invalidate: [queryKeys.vehicles.all], successMessage: "Vehicle removed" },
  );

  const vehicles = query.data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="My vehicles"
        description="The vehicles we can book service for."
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden />
            Add vehicle
          </Button>
        }
      />

      {query.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <CardSkeletons count={3} />
        </div>
      ) : null}

      {query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : null}

      {query.isSuccess && vehicles.length === 0 ? (
        <Card>
          <EmptyState
            icon={Car}
            title="No vehicles yet"
            description="Add your car so we know what we will be working on when you book."
            action={
              <Button
                size="sm"
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                <Plus className="size-4" aria-hidden />
                Add vehicle
              </Button>
            }
          />
        </Card>
      ) : null}

      {vehicles.length > 0 ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {vehicles.map((vehicle) => (
            <li key={vehicle.id}>
              <Card className="flex h-full flex-col gap-4 p-5">
                <div className="flex items-start gap-3">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <Car className="size-5 text-muted-foreground" aria-hidden />
                  </div>
                  <div className="min-w-0">
                    <h2 className="truncate font-medium">{vehicle.display_name}</h2>
                    <p className="truncate text-sm text-muted-foreground">
                      {vehicle.color ?? "No colour on file"}
                    </p>
                  </div>
                </div>

                <dl className="space-y-1.5 text-sm">
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">License plate</dt>
                    <dd className="truncate font-mono">{vehicle.license_plate ?? "—"}</dd>
                  </div>
                  {vehicle.notes ? (
                    <div className="pt-1">
                      <dt className="text-muted-foreground">Notes</dt>
                      <dd className="mt-1 line-clamp-3 whitespace-pre-wrap">{vehicle.notes}</dd>
                    </div>
                  ) : null}
                </dl>

                <div className="mt-auto flex gap-2 pt-1">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      setEditing(vehicle);
                      setFormOpen(true);
                    }}
                  >
                    <Pencil className="size-4" aria-hidden />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${vehicle.display_name}`}
                    onClick={() => setRemoving(vehicle)}
                  >
                    <Trash2 className="size-4 text-destructive" aria-hidden />
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      ) : null}

      <VehicleFormDialog open={formOpen} onOpenChange={setFormOpen} vehicle={editing} />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.display_name ?? "this vehicle"}?`}
        description="It will no longer be available to book service for. This cannot be undone."
        confirmLabel="Remove vehicle"
        pendingLabel="Removing..."
        onConfirm={async () => {
          if (removing) await removeVehicle.mutateAsync(removing);
        }}
      />
    </div>
  );
}
