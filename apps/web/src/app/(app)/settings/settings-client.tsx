"use client";

import { Loader2, Plus, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { DataPanel, PanelFooter, PrimaryCell } from "@/components/data/data-panel";
import { FieldSelect } from "@/components/data/field-select";
import { PageHeader, SectionHeader, Toolbar } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { SearchInput } from "@/components/data/search-input";
import { Status } from "@/components/data/status-badge";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { fieldErrorsOf, usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDate } from "@/lib/format";
import { ROLE_LABELS } from "@/lib/permissions";
import { queryKeys } from "@/lib/query-keys";
import type { Member, Organization, Role } from "@/lib/types";

const ROLES: Role[] = ["OWNER", "MANAGER", "DISPATCHER", "TECHNICIAN", "ANALYST", "CUSTOMER"];
const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles"];

const ROLE_SUMMARY: Record<Role, string> = {
  OWNER: "Everything, including settings and who has access",
  MANAGER: "Staff, customers, bookings and jobs",
  DISPATCHER: "Schedules, bookings and assignments",
  TECHNICIAN: "Their own jobs and availability",
  ANALYST: "Reads operational data; changes nothing",
  CUSTOMER: "Their own bookings and history",
};

function BusinessDetails({ organization, editable }: { organization: Organization; editable: boolean }) {
  const router = useRouter();
  const [values, setValues] = useState({
    name: organization.name,
    email: organization.email,
    phone: organization.phone ?? "",
    address: organization.address ?? "",
    timezone: organization.timezone,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useResourceMutation<void, Organization>(
    () =>
      apiFetchData<Organization>("organizations/current", {
        method: "PATCH",
        body: JSON.stringify({ ...values, phone: values.phone || null, address: values.address || null }),
      }),
    { invalidate: [queryKeys.organization.current], successMessage: "Business details saved" },
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!values.name.trim()) next.name = "Enter the business name.";
    if (!/^\S+@\S+\.\S+$/.test(values.email)) next.email = "Enter a valid email address.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    try {
      await save.mutateAsync();
      router.refresh();
    } catch (error) {
      setErrors(fieldErrorsOf(error));
    }
  }

  const field = (key: keyof typeof values, label: string, type = "text") => (
    <div className="space-y-1.5">
      <Label htmlFor={`business-${key}`}>{label}</Label>
      <Input
        id={`business-${key}`}
        type={type}
        value={values[key]}
        disabled={!editable || save.isPending}
        aria-invalid={Boolean(errors[key])}
        aria-describedby={errors[key] ? `business-${key}-error` : undefined}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
      />
      {errors[key] ? (
        <p id={`business-${key}-error`} className="text-[13px] text-destructive">
          {errors[key]}
        </p>
      ) : null}
    </div>
  );

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          {field("name", "Business name")}
          {field("email", "Contact email", "email")}
          {field("phone", "Phone", "tel")}
          <div className="space-y-1.5">
            <Label htmlFor="business-timezone">Timezone</Label>
            <FieldSelect
              id="business-timezone"
              label="Timezone"
              value={values.timezone}
              onChange={(timezone) => setValues({ ...values, timezone })}
              className="w-full"
            >
              {Array.from(new Set([values.timezone, ...TIMEZONES])).map((zone) => (
                <option key={zone} value={zone} disabled={!editable}>
                  {zone.replace("_", " ")}
                </option>
              ))}
            </FieldSelect>
          </div>
        </div>
        {field("address", "Business address")}
        <div className="flex items-center justify-between gap-3 border-t pt-4">
          <p className="text-[12px] text-muted-foreground">
            {editable ? "Schedules, reminders and working hours use this timezone." : "Only an owner can change business details."}
          </p>
          {editable ? (
            <Button type="submit" size="sm" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              {save.isPending ? "Saving..." : "Save changes"}
            </Button>
          ) : null}
        </div>
      </form>
    </Card>
  );
}

function AddMemberDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const empty = { email: "", first_name: "", last_name: "", role: "DISPATCHER" as Role, job_title: "" };
  const [values, setValues] = useState(empty);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const add = useResourceMutation<void, Member>(
    () =>
      apiFetchData<Member>("members", {
        method: "POST",
        body: JSON.stringify({ ...values, job_title: values.job_title || null }),
      }),
    {
      invalidate: [queryKeys.members.all, queryKeys.employees.all, queryKeys.customers.all],
      successMessage: (member) => `${member.full_name} added as ${ROLE_LABELS[member.role].toLowerCase()}`,
    },
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!values.first_name.trim()) next.first_name = "Enter a first name.";
    if (!values.last_name.trim()) next.last_name = "Enter a last name.";
    if (!/^\S+@\S+\.\S+$/.test(values.email)) next.email = "Enter a valid email address.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    try {
      await add.mutateAsync();
      setValues(empty);
      onOpenChange(false);
    } catch (error) {
      setErrors(fieldErrorsOf(error));
    }
  }

  const input = (key: "email" | "first_name" | "last_name" | "job_title", label: string, type = "text") => (
    <div className="space-y-1.5">
      <Label htmlFor={`member-${key}`}>{label}</Label>
      <Input
        id={`member-${key}`}
        type={type}
        value={values[key]}
        aria-invalid={Boolean(errors[key])}
        onChange={(event) => setValues({ ...values, [key]: event.target.value })}
      />
      {errors[key] ? <p className="text-[13px] text-destructive">{errors[key]}</p> : null}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a team member</DialogTitle>
          <DialogDescription>Give someone access to this business with one role.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            {input("first_name", "First name")}
            {input("last_name", "Last name")}
          </div>
          {input("email", "Email", "email")}
          <div className="space-y-1.5">
            <Label htmlFor="member-role">Role</Label>
            <FieldSelect
              id="member-role"
              label="Role"
              value={values.role}
              onChange={(role) => setValues({ ...values, role: role as Role })}
              className="w-full"
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </FieldSelect>
            <p className="text-[12px] text-muted-foreground">{ROLE_SUMMARY[values.role]}.</p>
          </div>
          {values.role === "TECHNICIAN" ? input("job_title", "Job title") : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={add.isPending}>
              {add.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              {add.isPending ? "Adding..." : "Add member"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Business settings and who has access.
 *
 * Owners change both; managers and analysts can see the team but not change it.
 * The API enforces the same split - these controls are hidden because they
 * would be refused, not in place of the refusal.
 */
export function SettingsClient({
  organization,
  currentUserId,
  canManageBusiness,
  canManageMembers,
}: {
  organization: Organization;
  currentUserId: string;
  canManageBusiness: boolean;
  canManageMembers: boolean;
}) {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [suspending, setSuspending] = useState<Member | null>(null);

  const params = { q, role: role || undefined, page, page_size: 20 };
  const members = usePagedResource<Member>(queryKeys.members.list(params), "members", params);

  const update = useResourceMutation<{ member: Member; body: Record<string, string> }, Member>(
    ({ member, body }) => apiFetchData<Member>(`members/${member.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    {
      invalidate: [queryKeys.members.all, queryKeys.employees.all],
      successMessage: (member) =>
        member.status === "SUSPENDED" ? `${member.full_name}'s access suspended` : `${member.full_name} is now ${ROLE_LABELS[member.role].toLowerCase()}`,
    },
  );

  const rows = members.data?.data ?? [];

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" description={`How ${organization.name} is set up, and who can sign in to it.`} />

      <section className="space-y-3">
        <SectionHeader title="Business details" />
        <BusinessDetails organization={organization} editable={canManageBusiness} />
      </section>

      <section className="space-y-3">
        <SectionHeader
          title="Team access"
          description="Each person has a role in this business. Roles decide what they can see and change."
          action={
            canManageMembers ? (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus className="size-3.5" aria-hidden />
                Add member
              </Button>
            ) : null
          }
        />
        <Toolbar className="justify-between">
          <SearchInput
            value={q}
            onChange={(next) => {
              setQ(next);
              setPage(1);
            }}
            label="Search members"
            placeholder="Name or email"
          />
          <FieldSelect
            label="Filter by role"
            value={role}
            onChange={(next) => {
              setRole(next);
              setPage(1);
            }}
            className="w-44"
          >
            <option value="">All roles</option>
            {ROLES.map((option) => (
              <option key={option} value={option}>
                {ROLE_LABELS[option]}
              </option>
            ))}
          </FieldSelect>
        </Toolbar>
        <DataPanel>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[240px]">Member</TableHead>
                  <TableHead className="min-w-[190px]">Role</TableHead>
                  <TableHead className="min-w-[120px]">Status</TableHead>
                  <TableHead className="min-w-[110px]">Added</TableHead>
                  {canManageMembers ? (
                    <TableHead className="w-28">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.isPending ? <TableSkeletonRows columns={canManageMembers ? 5 : 4} /> : null}
                {members.isError ? (
                  <TableRow>
                    <TableCell colSpan={5} className="p-0">
                      <ErrorState error={members.error} onRetry={() => members.refetch()} />
                    </TableCell>
                  </TableRow>
                ) : null}
                {members.isSuccess && rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="p-0">
                      <EmptyState icon={ShieldCheck} title="No members match" description="Try a different name or role." />
                    </TableCell>
                  </TableRow>
                ) : null}
                {rows.map((member) => {
                  const self = member.user_id === currentUserId;
                  return (
                    <TableRow key={member.id}>
                      <TableCell>
                        <PrimaryCell title={`${member.full_name}${self ? " (you)" : ""}`} subtitle={member.email} />
                      </TableCell>
                      <TableCell>
                        {canManageMembers && !self ? (
                          <FieldSelect
                            label={`Role for ${member.full_name}`}
                            value={member.role}
                            onChange={(next) => update.mutate({ member, body: { role: next } })}
                            className="w-44"
                          >
                            {ROLES.map((option) => (
                              <option key={option} value={option}>
                                {ROLE_LABELS[option]}
                              </option>
                            ))}
                          </FieldSelect>
                        ) : (
                          <span className="text-[13px]">{ROLE_LABELS[member.role]}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Status
                          label={member.status === "ACTIVE" ? (member.can_sign_in ? "Active" : "No sign-in yet") : "Suspended"}
                          tone={member.status === "ACTIVE" ? (member.can_sign_in ? "done" : "pending") : "muted"}
                        />
                      </TableCell>
                      <TableCell className="text-muted-foreground">{formatDate(member.created_at)}</TableCell>
                      {canManageMembers ? (
                        <TableCell className="text-right">
                          {self ? null : member.status === "ACTIVE" ? (
                            <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setSuspending(member)}>
                              Suspend
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => update.mutate({ member, body: { status: "ACTIVE" } })}
                            >
                              Reactivate
                            </Button>
                          )}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
          {members.data && members.data.meta.total > 0 ? (
            <PanelFooter>
              <PaginationControls meta={members.data.meta} onPageChange={setPage} noun="members" />
            </PanelFooter>
          ) : null}
        </DataPanel>
      </section>

      {canManageMembers ? <AddMemberDialog open={adding} onOpenChange={setAdding} /> : null}
      <ConfirmDialog
        open={suspending !== null}
        onOpenChange={(open) => !open && setSuspending(null)}
        title={`Suspend ${suspending?.full_name ?? "this member"}?`}
        description="They lose access to this business immediately. Their history stays, and you can reactivate them later."
        confirmLabel="Suspend access"
        pendingLabel="Suspending..."
        onConfirm={async () => {
          if (suspending) await update.mutateAsync({ member: suspending, body: { status: "SUSPENDED" } });
        }}
      />
    </div>
  );
}
