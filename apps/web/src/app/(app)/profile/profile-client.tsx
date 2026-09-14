"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldErrorsOf, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Customer } from "@/lib/types";

type Values = { first_name: string; last_name: string; phone: string; address: string };

function ProfileForm({ customer }: { customer: Customer }) {
  const [values, setValues] = useState<Values>({
    first_name: customer.user.first_name,
    last_name: customer.user.last_name,
    phone: customer.user.phone ?? "",
    address: customer.address ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useResourceMutation<void, Customer>(
    () =>
      apiFetchData<Customer>("customers/me", {
        method: "PATCH",
        body: JSON.stringify({ ...values, phone: values.phone || null, address: values.address || null }),
      }),
    { invalidate: [queryKeys.customers.me], successMessage: "Profile saved" },
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!values.first_name.trim()) next.first_name = "Enter your first name.";
    if (!values.last_name.trim()) next.last_name = "Enter your last name.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    try {
      await save.mutateAsync();
    } catch (error) {
      setErrors(fieldErrorsOf(error));
    }
  }

  const field = (key: keyof Values, label: string, props: React.ComponentProps<typeof Input> = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`profile-${key}`}>{label}</Label>
      <Input
        id={`profile-${key}`}
        value={values[key]}
        aria-invalid={Boolean(errors[key])}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
        disabled={save.isPending}
        {...props}
      />
      {errors[key] ? <p className="text-[13px] text-destructive">{errors[key]}</p> : null}
    </div>
  );

  return (
    <Card className="max-w-2xl p-5">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("first_name", "First name", { autoComplete: "given-name" })}
          {field("last_name", "Last name", { autoComplete: "family-name" })}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-email">Email</Label>
          <Input id="profile-email" value={customer.user.email} disabled aria-describedby="profile-email-help" />
          <p id="profile-email-help" className="text-[12px] text-muted-foreground">
            Your email signs you in and can&apos;t be changed here.
          </p>
        </div>
        {field("phone", "Phone", { type: "tel", autoComplete: "tel" })}
        {field("address", "Service address", { autoComplete: "street-address" })}
        <div className="flex justify-end border-t pt-4">
          <Button type="submit" size="sm" disabled={save.isPending}>
            {save.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
            {save.isPending ? "Saving..." : "Save profile"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

/** A customer's own details - the address technicians drive to. */
export function ProfileClient({ businessName }: { businessName: string }) {
  const query = useQuery<Customer, ApiError>({
    queryKey: queryKeys.customers.me,
    queryFn: () => apiFetchData<Customer>("customers/me"),
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Profile" description={`Your details at ${businessName}. Technicians use your service address for every visit.`} />
      {query.isPending ? (
        <Card className="max-w-2xl space-y-3 p-5">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-2/3" />
        </Card>
      ) : query.isError ? (
        <Card className="max-w-2xl">
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      ) : (
        <ProfileForm customer={query.data} />
      )}
    </div>
  );
}
