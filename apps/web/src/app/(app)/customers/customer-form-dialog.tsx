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
import type { Customer } from "@/lib/types";

const baseShape = {
  first_name: z.string().trim().min(1, "Enter a first name.").max(100),
  last_name: z.string().trim().min(1, "Enter a last name.").max(100),
  phone: z.string().trim().max(40).optional(),
  notes: z.string().trim().max(2000).optional(),
};

const createSchema = z.object({
  ...baseShape,
  email: z.string().trim().min(1, "Enter an email address.").email("Enter a valid email address."),
});
const editSchema = z.object(baseShape);

type FormValues = z.infer<typeof createSchema>;

export function CustomerFormDialog({
  open,
  onOpenChange,
  customer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  customer?: Customer | null;
}) {
  const editing = Boolean(customer);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver((editing ? editSchema : createSchema) as typeof createSchema),
    defaultValues: { email: "", first_name: "", last_name: "", phone: "", notes: "" },
  });

  useEffect(() => {
    if (!open) return;
    reset(
      customer
        ? {
            email: customer.user.email,
            first_name: customer.user.first_name,
            last_name: customer.user.last_name,
            phone: customer.user.phone ?? "",
            notes: customer.notes ?? "",
          }
        : { email: "", first_name: "", last_name: "", phone: "", notes: "" },
    );
  }, [open, customer, reset]);

  const mutation = useResourceMutation<FormValues, Customer>(
    (values) => {
      // Email identifies the person and is never reassigned on edit.
      const body = editing
        ? {
            first_name: values.first_name,
            last_name: values.last_name,
            phone: values.phone || null,
            notes: values.notes || null,
          }
        : { ...values, phone: values.phone || null, notes: values.notes || null };
      return apiFetchData<Customer>(editing ? `customers/${customer!.id}` : "customers", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    {
      invalidate: [queryKeys.customers.all, queryKeys.vehicles.all],
      successMessage: (result) =>
        editing ? `${result.user.full_name} updated` : `${result.user.full_name} added`,
    },
  );

  async function onSubmit(values: FormValues) {
    try {
      await mutation.mutateAsync(values);
      onOpenChange(false);
    } catch (error) {
      for (const [field, message] of Object.entries(fieldErrorsOf(error))) {
        if (field in createSchema.shape) setError(field as keyof FormValues, { message });
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit customer" : "Add a customer"}</DialogTitle>
          <DialogDescription>
            {editing
              ? "Update contact details and internal notes."
              : "Add someone to your customer list. They can be given sign-in access later."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="customer-first">First name</Label>
              <Input
                id="customer-first"
                autoComplete="given-name"
                aria-invalid={Boolean(errors.first_name)}
                {...register("first_name")}
              />
              {errors.first_name ? (
                <p className="text-sm text-destructive">{errors.first_name.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="customer-last">Last name</Label>
              <Input
                id="customer-last"
                autoComplete="family-name"
                aria-invalid={Boolean(errors.last_name)}
                {...register("last_name")}
              />
              {errors.last_name ? (
                <p className="text-sm text-destructive">{errors.last_name.message}</p>
              ) : null}
            </div>
          </div>

          {editing ? null : (
            <div className="space-y-2">
              <Label htmlFor="customer-email">Email</Label>
              <Input
                id="customer-email"
                type="email"
                autoComplete="email"
                aria-invalid={Boolean(errors.email)}
                {...register("email")}
              />
              {errors.email ? (
                <p className="text-sm text-destructive">{errors.email.message}</p>
              ) : null}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="customer-phone">Phone</Label>
            <Input
              id="customer-phone"
              type="tel"
              autoComplete="tel"
              placeholder="+1 (415) 555-0100"
              {...register("phone")}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="customer-notes">Internal notes</Label>
            <Textarea
              id="customer-notes"
              rows={3}
              placeholder="Only your team sees this."
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
                "Add customer"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
