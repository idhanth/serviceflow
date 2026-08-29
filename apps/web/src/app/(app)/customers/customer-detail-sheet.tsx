"use client";

import { Car, Mail, Phone, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { VehicleFormDialog } from "@/components/vehicles/vehicle-form-dialog";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetch } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Customer, Vehicle } from "@/lib/types";

export function CustomerDetailSheet({
  customer,
  onOpenChange,
}: {
  customer: Customer | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [vehicleFormOpen, setVehicleFormOpen] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState<Vehicle | null>(null);
  const [removing, setRemoving] = useState<Vehicle | null>(null);

  const params = { customer_id: customer?.id, page_size: 50 };
  const vehicles = usePagedResource<Vehicle>(
    queryKeys.vehicles.list(params),
    "vehicles",
    params,
    { enabled: Boolean(customer) },
  );

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

  return (
    <>
      <Sheet open={customer !== null} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
          {customer ? (
            <>
              <SheetHeader>
                <SheetTitle>{customer.user.full_name}</SheetTitle>
                <SheetDescription>
                  Customer since {formatDate(customer.created_at)}
                </SheetDescription>
              </SheetHeader>

              <div className="space-y-6 px-4 pb-6">
                <section className="space-y-2">
                  <a
                    href={`mailto:${customer.user.email}`}
                    className="flex items-center gap-2 text-sm hover:underline"
                  >
                    <Mail className="size-4 text-muted-foreground" aria-hidden />
                    {customer.user.email}
                  </a>
                  {customer.user.phone ? (
                    <a
                      href={`tel:${customer.user.phone}`}
                      className="flex items-center gap-2 text-sm hover:underline"
                    >
                      <Phone className="size-4 text-muted-foreground" aria-hidden />
                      {customer.user.phone}
                    </a>
                  ) : (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Phone className="size-4" aria-hidden />
                      No phone number
                    </p>
                  )}
                </section>

                {customer.notes ? (
                  <section className="space-y-1.5">
                    <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Internal notes
                    </h3>
                    <p className="whitespace-pre-wrap rounded-lg bg-muted/60 p-3 text-sm">
                      {customer.notes}
                    </p>
                  </section>
                ) : null}

                <Separator />

                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-medium">Vehicles</h3>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEditingVehicle(null);
                        setVehicleFormOpen(true);
                      }}
                    >
                      <Plus className="size-4" aria-hidden />
                      Add
                    </Button>
                  </div>

                  {vehicles.isPending ? (
                    <div className="space-y-2">
                      {[0, 1].map((index) => (
                        <Skeleton key={index} className="h-16 w-full rounded-lg" />
                      ))}
                    </div>
                  ) : null}

                  {vehicles.isError ? (
                    <ErrorState error={vehicles.error} onRetry={() => vehicles.refetch()} />
                  ) : null}

                  {vehicles.isSuccess && vehicles.data.data.length === 0 ? (
                    <EmptyState
                      icon={Car}
                      title="No vehicles yet"
                      description="Add a vehicle so this customer has something to book service for."
                    />
                  ) : null}

                  <ul className="space-y-2">
                    {(vehicles.data?.data ?? []).map((vehicle) => (
                      <li
                        key={vehicle.id}
                        className="flex items-start justify-between gap-3 rounded-lg border p-3"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-medium">{vehicle.display_name}</p>
                          <p className="truncate text-sm text-muted-foreground">
                            {[vehicle.color, vehicle.license_plate].filter(Boolean).join(" · ") ||
                              "No colour or plate on file"}
                          </p>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEditingVehicle(vehicle);
                              setVehicleFormOpen(true);
                            }}
                          >
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
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>

      <VehicleFormDialog
        open={vehicleFormOpen}
        onOpenChange={setVehicleFormOpen}
        vehicle={editingVehicle}
        customerId={customer?.id}
        ownerName={customer?.user.full_name}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.display_name ?? "this vehicle"}?`}
        description="The vehicle is deleted from this customer's account. This cannot be undone."
        confirmLabel="Remove vehicle"
        pendingLabel="Removing..."
        onConfirm={async () => {
          if (removing) await removeVehicle.mutateAsync(removing);
        }}
      />
    </>
  );
}
