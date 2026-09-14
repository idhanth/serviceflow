"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Loader2, Lock, Plus } from "lucide-react";
import { useState } from "react";

import { DataPanel, PrimaryCell } from "@/components/data/data-panel";
import { FieldSelect } from "@/components/data/field-select";
import { PageHeader } from "@/components/data/page-header";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldErrorsOf, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData, ApiError } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { TenantSummary } from "@/lib/types";

const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles"];

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function CreateTenantDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const empty = {
    name: "",
    slug: "",
    email: "",
    timezone: "America/Chicago",
    owner_first_name: "",
    owner_last_name: "",
    owner_email: "",
  };
  const [values, setValues] = useState(empty);
  const [slugTouched, setSlugTouched] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useResourceMutation<void, TenantSummary>(
    () => apiFetchData<TenantSummary>("platform/tenants", { method: "POST", body: JSON.stringify(values) }),
    { invalidate: [queryKeys.platform.tenants], successMessage: (tenant) => `${tenant.name} created` },
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (values.name.trim().length < 2) next.name = "Enter the business name.";
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(values.slug)) next.slug = "Lowercase letters, numbers and dashes.";
    for (const key of ["email", "owner_email"] as const) {
      if (!/^\S+@\S+\.\S+$/.test(values[key])) next[key] = "Enter a valid email address.";
    }
    if (!values.owner_first_name.trim()) next.owner_first_name = "Required.";
    if (!values.owner_last_name.trim()) next.owner_last_name = "Required.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    try {
      await create.mutateAsync();
      setValues(empty);
      setSlugTouched(false);
      onOpenChange(false);
    } catch (error) {
      setErrors(fieldErrorsOf(error));
    }
  }

  const input = (key: keyof typeof values, label: string, type = "text") => (
    <div className="space-y-1.5">
      <Label htmlFor={`tenant-${key}`}>{label}</Label>
      <Input
        id={`tenant-${key}`}
        type={type}
        value={values[key]}
        aria-invalid={Boolean(errors[key])}
        onChange={(event) => {
          const value = event.target.value;
          if (key === "slug") setSlugTouched(true);
          setValues((current) => ({
            ...current,
            [key]: value,
            ...(key === "name" && !slugTouched ? { slug: slugify(value) } : {}),
          }));
        }}
      />
      {errors[key] ? <p className="text-[13px] text-destructive">{errors[key]}</p> : null}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New business</DialogTitle>
          <DialogDescription>Creates an empty tenant and its first owner, who sets up everything else.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            {input("name", "Business name")}
            {input("slug", "Address slug")}
            {input("email", "Business email", "email")}
            <div className="space-y-1.5">
              <Label htmlFor="tenant-timezone">Timezone</Label>
              <FieldSelect
                id="tenant-timezone"
                label="Timezone"
                value={values.timezone}
                onChange={(timezone) => setValues({ ...values, timezone })}
                className="w-full"
              >
                {TIMEZONES.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone.replace("_", " ")}
                  </option>
                ))}
              </FieldSelect>
            </div>
          </div>
          <fieldset className="space-y-3 border-t pt-4">
            <legend className="text-[13px] font-medium">First owner</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {input("owner_first_name", "First name")}
              {input("owner_last_name", "Last name")}
            </div>
            {input("owner_email", "Email", "email")}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              {create.isPending ? "Creating..." : "Create business"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The platform view: which businesses exist and how large each is.
 *
 * Counts only. A platform administrator holds no membership in any business,
 * so the API refuses them every tenant's customers, bookings and jobs.
 */
export function PlatformClient() {
  const [creating, setCreating] = useState(false);
  const query = useQuery<TenantSummary[], ApiError>({
    queryKey: queryKeys.platform.tenants,
    queryFn: () => apiFetchData<TenantSummary[]>("platform/tenants"),
  });
  const tenants = query.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Businesses"
        description="Every tenant on the platform, with its size. Records inside each business stay private to it."
        action={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="size-3.5" aria-hidden />
            New business
          </Button>
        }
      />

      <p className="flex items-start gap-2 rounded-md border bg-muted/30 px-3 py-2.5 text-[13px] text-muted-foreground">
        <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Platform administration can create businesses and see their size, but can&apos;t open their customers, bookings or jobs.
        That access comes only from a membership inside the business.
      </p>

      <DataPanel>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[240px]">Business</TableHead>
                <TableHead className="min-w-[140px]">Timezone</TableHead>
                {["Members", "Employees", "Customers", "Bookings", "Jobs"].map((label) => (
                  <TableHead key={label} className="min-w-[90px] text-right">
                    {label}
                  </TableHead>
                ))}
                <TableHead className="min-w-[110px]">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={8} rows={3} /> : null}
              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={8} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}
              {query.isSuccess && tenants.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="p-0">
                    <EmptyState icon={Building2} title="No businesses yet" description="Create the first one to get started." />
                  </TableCell>
                </TableRow>
              ) : null}
              {tenants.map((tenant) => (
                <TableRow key={tenant.id}>
                  <TableCell>
                    <PrimaryCell title={tenant.name} subtitle={tenant.slug} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{tenant.timezone.replace("_", " ")}</TableCell>
                  {[tenant.members, tenant.employees, tenant.customers, tenant.bookings, tenant.jobs].map((value, index) => (
                    <TableCell key={index} className="text-right tabular-nums">
                      {value.toLocaleString()}
                    </TableCell>
                  ))}
                  <TableCell className="text-muted-foreground">{formatDate(tenant.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataPanel>

      <CreateTenantDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
