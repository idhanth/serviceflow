"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { FormSection } from "@/components/data/form-section";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldErrorsOf, usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDuration } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Employee, Service } from "@/lib/types";

const baseShape = {
  first_name: z.string().trim().min(1, "Enter a first name.").max(100),
  last_name: z.string().trim().min(1, "Enter a last name.").max(100),
  job_title: z.string().trim().min(1, "Enter a job title.").max(120),
  phone: z.string().trim().max(40).optional(),
  service_ids: z.array(z.string()),
};

const createSchema = z.object({
  ...baseShape,
  email: z.string().trim().min(1, "Enter an email address.").email("Enter a valid email address."),
});
const editSchema = z.object(baseShape);

type FormValues = z.infer<typeof createSchema>;

export function EmployeeFormDialog({
  open,
  onOpenChange,
  employee,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employee?: Employee | null;
}) {
  const editing = Boolean(employee);

  const serviceParams = { active: true, page_size: 100 };
  const services = usePagedResource<Service>(
    queryKeys.services.list(serviceParams),
    "services",
    serviceParams,
    { enabled: open },
  );

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver((editing ? editSchema : createSchema) as typeof createSchema),
    defaultValues: {
      email: "",
      first_name: "",
      last_name: "",
      job_title: "Technician",
      phone: "",
      service_ids: [],
    },
  });

  useEffect(() => {
    if (!open) return;
    reset(
      employee
        ? {
            email: employee.user.email,
            first_name: employee.user.first_name,
            last_name: employee.user.last_name,
            job_title: employee.job_title,
            phone: employee.user.phone ?? "",
            service_ids: employee.services.map((service) => service.id),
          }
        : {
            email: "",
            first_name: "",
            last_name: "",
            job_title: "Technician",
            phone: "",
            service_ids: [],
          },
    );
  }, [open, employee, reset]);

  const mutation = useResourceMutation<FormValues, Employee>(
    (values) => {
      const body = editing
        ? {
            first_name: values.first_name,
            last_name: values.last_name,
            job_title: values.job_title,
            phone: values.phone || null,
            service_ids: values.service_ids,
          }
        : { ...values, phone: values.phone || null };
      return apiFetchData<Employee>(editing ? `employees/${employee!.id}` : "employees", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
    },
    {
      invalidate: [queryKeys.employees.all, queryKeys.services.all],
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
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit employee" : "Add an employee"}</DialogTitle>
          <DialogDescription>
            Qualifications decide who can be assigned to which service.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <FormSection title="Person">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="employee-first">First name</Label>
              <Input
                id="employee-first"
                autoComplete="given-name"
                aria-invalid={Boolean(errors.first_name)}
                {...register("first_name")}
              />
              {errors.first_name ? (
                <p className="text-sm text-destructive">{errors.first_name.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="employee-last">Last name</Label>
              <Input
                id="employee-last"
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
              <Label htmlFor="employee-email">Email</Label>
              <Input
                id="employee-email"
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

          </FormSection>

          <FormSection title="Role">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="employee-title">Job title</Label>
              <Input
                id="employee-title"
                aria-invalid={Boolean(errors.job_title)}
                {...register("job_title")}
              />
              {errors.job_title ? (
                <p className="text-sm text-destructive">{errors.job_title.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="employee-phone">Phone</Label>
              <Input id="employee-phone" type="tel" autoComplete="tel" {...register("phone")} />
            </div>
          </div>
          </FormSection>

          <FormSection
            title="Qualifications"
            description="Only qualified people can be assigned to a service."
          >
          <fieldset className="space-y-2">
            <legend className="sr-only">Services they can perform</legend>
            {services.isPending ? (
              <div className="space-y-2">
                {[0, 1, 2].map((index) => (
                  <Skeleton key={index} className="h-9 w-full rounded-lg" />
                ))}
              </div>
            ) : null}

            {services.isSuccess && services.data.data.length === 0 ? (
              <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                No active services yet. Add services first, then assign them here.
              </p>
            ) : null}

            <Controller
              control={control}
              name="service_ids"
              render={({ field }) => (
                <div className="grid gap-1.5 sm:grid-cols-2">
                  {(services.data?.data ?? []).map((service) => {
                    const checked = field.value.includes(service.id);
                    return (
                      <label
                        key={service.id}
                        // A checkbox list, not six bordered boxes: the border
                        // around each option competes with the dialog's own.
                        className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors duration-75 hover:bg-muted/60"
                      >
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(next) =>
                            field.onChange(
                              next
                                ? [...field.value, service.id]
                                : field.value.filter((id) => id !== service.id),
                            )
                          }
                        />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{service.name}</span>
                          <span className="block text-xs text-muted-foreground">
                            {formatDuration(service.duration_minutes)}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            />
          </fieldset>
          </FormSection>

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
                "Add employee"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
