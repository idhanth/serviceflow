"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { fieldErrorsOf, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Vehicle } from "@/lib/types";

const CURRENT_YEAR = new Date().getFullYear();

const schema = z.object({
  year: z
    .number({ message: "Enter a year." })
    .int()
    .min(1900, "Enter a year from 1900 onwards.")
    .max(CURRENT_YEAR + 2, `Enter a year up to ${CURRENT_YEAR + 2}.`),
  make: z.string().trim().min(1, "Enter the make.").max(60),
  model: z.string().trim().min(1, "Enter the model.").max(60),
  color: z.string().trim().max(40).optional(),
  license_plate: z.string().trim().max(20).optional(),
  notes: z.string().trim().max(2000).optional(),
});

type FormValues = z.infer<typeof schema>;

/**
 * Used by both the admin vehicle pages and a customer's own garage. The owner is
 * passed explicitly by admins; for a customer the API derives it from the session,
 * so this component never has to know which case it is in.
 */
export function VehicleFormDialog({
  open,
  onOpenChange,
  vehicle,
  customerId,
  ownerName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vehicle?: Vehicle | null;
  customerId?: string;
  ownerName?: string;
}) {
  const editing = Boolean(vehicle);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { year: CURRENT_YEAR, make: "", model: "", color: "", license_plate: "", notes: "" },
  });

  useEffect(() => {
    if (!open) return;
    reset(
      vehicle
        ? {
            year: vehicle.year,
            make: vehicle.make,
            model: vehicle.model,
            color: vehicle.color ?? "",
            license_plate: vehicle.license_plate ?? "",
            notes: vehicle.notes ?? "",
          }
        : {
            year: CURRENT_YEAR,
            make: "",
            model: "",
            color: "",
            license_plate: "",
            notes: "",
          },
    );
  }, [open, vehicle, reset]);

  const mutation = useResourceMutation<FormValues, Vehicle>(
    (values) =>
      apiFetchData<Vehicle>(editing ? `vehicles/${vehicle!.id}` : "vehicles", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify({
          ...values,
          color: values.color || null,
          license_plate: values.license_plate || null,
          notes: values.notes || null,
          ...(editing || !customerId ? {} : { customer_id: customerId }),
        }),
      }),
    {
      invalidate: [queryKeys.vehicles.all, queryKeys.customers.all],
      successMessage: (result) =>
        editing ? `${result.display_name} updated` : `${result.display_name} added`,
    },
  );

  async function onSubmit(values: FormValues) {
    try {
      await mutation.mutateAsync(values);
      onOpenChange(false);
    } catch (error) {
      for (const [field, message] of Object.entries(fieldErrorsOf(error))) {
        if (field in schema.shape) setError(field as keyof FormValues, { message });
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit vehicle" : "Add a vehicle"}</DialogTitle>
          <DialogDescription>
            {ownerName
              ? `This vehicle belongs to ${ownerName}.`
              : "Tell us what we will be working on."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="vehicle-year">Year</Label>
              <Input
                id="vehicle-year"
                type="number"
                min={1900}
                max={CURRENT_YEAR + 2}
                aria-invalid={Boolean(errors.year)}
                {...register("year", { valueAsNumber: true })}
              />
              {errors.year ? (
                <p className="text-sm text-destructive">{errors.year.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="vehicle-make">Make</Label>
              <Input
                id="vehicle-make"
                placeholder="BMW"
                aria-invalid={Boolean(errors.make)}
                {...register("make")}
              />
              {errors.make ? (
                <p className="text-sm text-destructive">{errors.make.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="vehicle-model">Model</Label>
              <Input
                id="vehicle-model"
                placeholder="M3"
                aria-invalid={Boolean(errors.model)}
                {...register("model")}
              />
              {errors.model ? (
                <p className="text-sm text-destructive">{errors.model.message}</p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="vehicle-color">Colour</Label>
              <Input id="vehicle-color" placeholder="Alpine White" {...register("color")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="vehicle-plate">License plate</Label>
              <Input id="vehicle-plate" placeholder="ABC123" {...register("license_plate")} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="vehicle-notes">Notes</Label>
            <Textarea
              id="vehicle-notes"
              rows={3}
              placeholder="Anything we should know - paint condition, pet hair, aftermarket wrap."
              {...register("notes")}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Saving...
                </>
              ) : editing ? (
                "Save changes"
              ) : (
                "Add vehicle"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
