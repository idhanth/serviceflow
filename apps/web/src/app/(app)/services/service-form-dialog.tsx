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
import type { Service } from "@/lib/types";

const schema = z.object({
  name: z.string().trim().min(1, "Enter a service name.").max(120),
  description: z.string().trim().max(2000).optional(),
  base_price: z
    .string()
    .min(1, "Enter a price.")
    .refine((value) => /^\d+(\.\d{1,2})?$/.test(value), "Use a number like 195 or 195.00."),
  duration_minutes: z
    .number({ message: "Enter a duration in minutes." })
    .int("Use whole minutes.")
    .positive("Duration must be more than zero.")
    .max(1440, "Keep it under 24 hours."),
});

type FormValues = z.infer<typeof schema>;

export function ServiceFormDialog({
  open,
  onOpenChange,
  service,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  service?: Service | null;
}) {
  const editing = Boolean(service);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "", base_price: "", duration_minutes: 60 },
  });

  useEffect(() => {
    if (!open) return;
    reset(
      service
        ? {
            name: service.name,
            description: service.description ?? "",
            base_price: service.base_price,
            duration_minutes: service.duration_minutes,
          }
        : { name: "", description: "", base_price: "", duration_minutes: 60 },
    );
  }, [open, service, reset]);

  const mutation = useResourceMutation<FormValues, Service>(
    (values) =>
      apiFetchData<Service>(editing ? `services/${service!.id}` : "services", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify({ ...values, description: values.description || null }),
      }),
    {
      invalidate: [queryKeys.services.all, queryKeys.employees.all],
      successMessage: (result) => (editing ? `${result.name} updated` : `${result.name} added`),
    },
  );

  async function onSubmit(values: FormValues) {
    try {
      await mutation.mutateAsync(values);
      onOpenChange(false);
    } catch (error) {
      // Surface server-side field errors (e.g. a duplicate name) next to the input.
      for (const [field, message] of Object.entries(fieldErrorsOf(error))) {
        if (field in schema.shape) setError(field as keyof FormValues, { message });
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit service" : "Add a service"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "Changes apply to new bookings. Existing jobs keep their original details."
              : "Duration determines how long the appointment blocks on the schedule."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="service-name">Name</Label>
            <Input
              id="service-name"
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? "service-name-error" : undefined}
              {...register("name")}
            />
            {errors.name ? (
              <p id="service-name-error" className="text-sm text-destructive">
                {errors.name.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="service-description">Description</Label>
            <Textarea id="service-description" rows={3} {...register("description")} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="service-price">Base price (USD)</Label>
              <Input
                id="service-price"
                inputMode="decimal"
                placeholder="195.00"
                aria-invalid={Boolean(errors.base_price)}
                aria-describedby={errors.base_price ? "service-price-error" : undefined}
                {...register("base_price")}
              />
              {errors.base_price ? (
                <p id="service-price-error" className="text-sm text-destructive">
                  {errors.base_price.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="service-duration">Duration (minutes)</Label>
              <Input
                id="service-duration"
                type="number"
                min={1}
                step={5}
                aria-invalid={Boolean(errors.duration_minutes)}
                aria-describedby={errors.duration_minutes ? "service-duration-error" : undefined}
                {...register("duration_minutes", { valueAsNumber: true })}
              />
              {errors.duration_minutes ? (
                <p id="service-duration-error" className="text-sm text-destructive">
                  {errors.duration_minutes.message}
                </p>
              ) : null}
            </div>
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
                "Add service"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
