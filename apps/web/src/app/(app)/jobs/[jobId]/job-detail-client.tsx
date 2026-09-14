"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Play,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { ErrorState } from "@/components/data/states";
import { NotesPanel } from "@/components/jobs/notes-panel";
import { PhotoGallery } from "@/components/jobs/photo-gallery";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, ApiError, apiFetchData } from "@/lib/api-client";
import { formatDuration, formatPrice, formatRelative, formatTime, formatWindow } from "@/lib/format";
import { OPERATIONS_KEYS, queryKeys } from "@/lib/query-keys";
import type { AssignableEmployee, AuditEntry, Job, Paged } from "@/lib/types";
import { cn } from "@/lib/utils";

const HISTORY_LABELS: Partial<Record<AuditEntry["action"], string>> = {
  BOOKING_CREATED: "Booked",
  BOOKING_CONFIRMED: "Booking confirmed",
  BOOKING_RESCHEDULED: "Rescheduled",
  BOOKING_CANCELLED: "Booking cancelled",
  BOOKING_REJECTED: "Booking declined",
  JOB_ASSIGNED: "Technician assigned",
  JOB_REASSIGNED: "Technician changed",
  JOB_STARTED: "Work started",
  JOB_COMPLETED: "Work completed",
  JOB_CANCELLED: "Job cancelled",
  NOTE_ADDED: "Note added",
  NOTE_DELETED: "Note removed",
  PHOTO_DELETED: "Photo removed",
};

function TechnicianPicker({
  job,
  onAssigned,
}: {
  job: Job;
  onAssigned: () => void;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);

  const candidates = useQuery<{ data: AssignableEmployee[] }, ApiError>({
    queryKey: queryKeys.bookings.assignable(job.booking_id),
    queryFn: () => apiFetch<{ data: AssignableEmployee[] }>(`bookings/${job.booking_id}/assignable-employees`),
  });

  const assign = useResourceMutation<string, Job>(
    (employeeId) =>
      apiFetchData<Job>(`jobs/${job.id}/assign`, {
        method: "POST",
        body: JSON.stringify({ employee_id: employeeId }),
      }),
    {
      invalidate: [...OPERATIONS_KEYS, queryKeys.bookings.assignable(job.booking_id)],
      successMessage: (result) => `${result.employee?.full_name ?? "Technician"} is assigned`,
    },
  );

  async function submit() {
    if (!chosen) return;
    setConflict(null);
    try {
      await assign.mutateAsync(chosen);
      setChosen(null);
      onAssigned();
    } catch (error) {
      // A conflict is explained inline, next to the choice that caused it.
      if (error instanceof ApiError && error.status === 409) setConflict(errorMessage(error, ""));
    }
  }

  const list = (candidates.data?.data ?? []).filter((candidate) => candidate.id !== job.employee?.id);

  return (
    <section className="space-y-2.5" aria-label="Assign a technician">
      <h3 className="text-[13px] font-medium">{job.employee ? "Reassign" : "Assign a technician"}</h3>
      {candidates.isPending ? <Skeleton className="h-24 w-full" /> : null}
      {candidates.isError ? <ErrorState error={candidates.error} onRetry={() => candidates.refetch()} /> : null}
      {candidates.isSuccess && list.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Nobody else on the team is qualified for {job.service.name}.
        </p>
      ) : null}
      {list.length > 0 ? (
        <div className="divide-y overflow-hidden rounded-md border" role="radiogroup" aria-label="Technicians">
          {list.map((candidate) => (
            <label
              key={candidate.id}
              className={cn(
                "flex items-start gap-3 px-3 py-2 transition-colors duration-75",
                candidate.assignable ? "cursor-pointer hover:bg-muted/50" : "cursor-not-allowed",
                chosen === candidate.id && "bg-accent-solid/[0.07]",
              )}
            >
              <input
                type="radio"
                name={`assign-${job.id}`}
                className="mt-1 size-3.5 accent-[var(--accent-solid)]"
                checked={chosen === candidate.id}
                disabled={!candidate.assignable}
                onChange={() => {
                  setChosen(candidate.id);
                  setConflict(null);
                }}
              />
              <span className="min-w-0 flex-1">
                <span className={cn("block truncate text-[13px] font-medium", !candidate.assignable && "text-muted-foreground")}>
                  {candidate.full_name}
                </span>
                <span className="block text-[12px] text-muted-foreground">
                  {candidate.reason ??
                    `${candidate.jobs_today} ${candidate.jobs_today === 1 ? "job" : "jobs"} that day`}
                </span>
              </span>
            </label>
          ))}
        </div>
      ) : null}
      {conflict ? (
        <p role="alert" className="flex items-start gap-2 rounded-md border border-status-danger/25 bg-status-danger/10 p-2.5 text-[13px]">
          <AlertCircle className="mt-px size-3.5 shrink-0 text-status-danger" aria-hidden />
          {conflict}
        </p>
      ) : null}
      <Button className="w-full" disabled={!chosen || assign.isPending} onClick={submit}>
        {assign.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
        {assign.isPending ? "Assigning..." : job.employee ? "Reassign job" : "Assign and confirm"}
      </Button>
    </section>
  );
}

export function JobDetailClient({
  jobId,
  timeZone,
  canDispatch,
  canWork,
  canOpenBooking,
  canReadHistory,
  backHref,
}: {
  jobId: string;
  timeZone: string;
  canDispatch: boolean;
  canWork: boolean;
  canOpenBooking: boolean;
  canReadHistory: boolean;
  backHref: string;
}) {
  const [notes, setNotes] = useState("");
  const [notesReady, setNotesReady] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const query = useQuery<{ data: Job }, ApiError>({
    queryKey: queryKeys.jobs.detail(jobId),
    queryFn: () => apiFetch<{ data: Job }>(`jobs/${jobId}`),
  });
  const job = query.data?.data;

  const history = useQuery<AuditEntry[], ApiError>({
    queryKey: queryKeys.activity.list({ job: jobId, booking: job?.booking_id }),
    enabled: canReadHistory && Boolean(job),
    queryFn: async () => {
      const [forJob, forBooking] = await Promise.all([
        apiFetch<Paged<AuditEntry>>(`activity?resource_id=${jobId}&page_size=50`),
        apiFetch<Paged<AuditEntry>>(`activity?resource_id=${job!.booking_id}&page_size=50`),
      ]);
      return [...forJob.data, ...forBooking.data].sort((a, b) => b.created_at.localeCompare(a.created_at));
    },
  });

  // Seed the notes box once, without an effect that would fight the user's typing.
  if (job && !notesReady) {
    setNotes(job.internal_notes ?? "");
    setNotesReady(true);
  }

  const invalidate = [...OPERATIONS_KEYS, queryKeys.activity.all];
  const start = useResourceMutation<void, Job>(
    () => apiFetchData<Job>(`jobs/${jobId}/start`, { method: "POST" }),
    { invalidate, successMessage: "Job started" },
  );
  const complete = useResourceMutation<void, Job>(
    () =>
      apiFetchData<Job>(`jobs/${jobId}/complete`, {
        method: "POST",
        body: JSON.stringify({ internal_notes: notes.trim() || null }),
      }),
    { invalidate, successMessage: "Job completed" },
  );
  const cancel = useResourceMutation<void, Job>(
    () => apiFetchData<Job>(`jobs/${jobId}/cancel`, { method: "POST" }),
    { invalidate, successMessage: "Job and booking cancelled" },
  );
  const busy = start.isPending || complete.isPending || cancel.isPending;

  if (query.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="space-y-4 p-5 lg:col-span-2">
            <Skeleton className="h-6 w-2/5" />
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="h-24 w-full" />
          </Card>
          <Card className="space-y-3 p-5">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-16 w-full" />
          </Card>
        </div>
      </div>
    );
  }

  if (query.isError || !job) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href={backHref} />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back
        </Button>
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      </div>
    );
  }

  const open = job.status === "NEW" || job.status === "SCHEDULED";
  const closed = job.status === "COMPLETED" || job.status === "CANCELLED";
  const steps = [
    { label: "Booked", detail: formatRelative(job.created_at), done: true },
    {
      label: job.employee ? "Assigned" : "Needs a technician",
      detail: job.employee ? `to ${job.employee.full_name}` : "Not yet",
      done: Boolean(job.employee),
    },
    { label: "Started", detail: job.started_at ? formatTime(job.started_at, timeZone) : "Not yet", done: Boolean(job.started_at) },
    { label: "Completed", detail: job.completed_at ? formatTime(job.completed_at, timeZone) : "Not yet", done: Boolean(job.completed_at) },
  ];

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href={backHref} />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">{job.service.name}</h1>
          <JobStatusBadge status={job.status} variant="chip" />
        </div>
        <p className="text-[13px] text-muted-foreground">
          {formatWindow(job.scheduled_start, job.scheduled_end, timeZone)} · {formatDuration(job.service.duration_minutes)} ·{" "}
          {formatPrice(job.service.base_price)}
        </p>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Card className="space-y-5 p-5 lg:col-span-2">
          <section className="grid gap-5 sm:grid-cols-2">
            <div className="min-w-0 space-y-1">
              <h2 className="text-[12px] text-muted-foreground">Customer</h2>
              <p className="flex items-center gap-2 text-[14px] font-medium">
                <UserRound className="size-4 text-muted-foreground" aria-hidden />
                {job.customer.full_name}
              </p>
              <a href={`mailto:${job.customer.email}`} className="focus-ring flex items-center gap-2 text-[13px] text-muted-foreground hover:underline">
                <Mail className="size-3.5" aria-hidden />
                <span className="truncate">{job.customer.email}</span>
              </a>
              {job.customer.phone ? (
                <a href={`tel:${job.customer.phone}`} className="focus-ring flex items-center gap-2 text-[13px] text-muted-foreground hover:underline">
                  <Phone className="size-3.5" aria-hidden />
                  {job.customer.phone}
                </a>
              ) : null}
            </div>
            <div className="min-w-0 space-y-1">
              <h2 className="text-[12px] text-muted-foreground">Service address</h2>
              {job.customer.address ? (
                <a
                  href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(job.customer.address)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="focus-ring flex items-start gap-2 text-[14px] font-medium hover:underline"
                >
                  <MapPin className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  {job.customer.address}
                </a>
              ) : (
                <p className="text-[13px] text-muted-foreground">No address on file</p>
              )}
              <p className="flex items-center gap-2 pt-1 text-[13px] text-muted-foreground">
                <ClipboardList className="size-3.5" aria-hidden />
                {canOpenBooking ? (
                  <Link href={`/bookings/${job.booking_id}`} className="focus-ring hover:underline">
                    Related booking
                  </Link>
                ) : (
                  "Booking"
                )}
                <BookingStatusBadge status={job.booking_status} />
              </p>
            </div>
          </section>

          {job.customer_notes ? (
            <>
              <Separator />
              <section className="space-y-1.5">
                <h2 className="text-[12px] text-muted-foreground">What the customer asked for</h2>
                <p className="whitespace-pre-wrap border-l-2 border-border pl-3 text-[13px]">{job.customer_notes}</p>
              </section>
            </>
          ) : null}

          {closed ? (
            notes ? (
              <section className="space-y-1.5 border-t pt-5">
                <h2 className="text-[12px] text-muted-foreground">Completion summary</h2>
                <p className="whitespace-pre-wrap border-l-2 border-border pl-3 text-[13px]">{notes}</p>
              </section>
            ) : null
          ) : canWork ? (
            <section className="space-y-2 border-t pt-5">
              <Label htmlFor="completion-summary">Completion summary</Label>
              <Textarea
                id="completion-summary"
                rows={3}
                maxLength={2000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                aria-describedby="completion-summary-help"
              />
              <p id="completion-summary-help" className="text-[12px] text-muted-foreground">
                Saved when the job is marked complete. Internal only - the customer never sees it.
              </p>
            </section>
          ) : null}
        </Card>

        <Card className="h-fit space-y-4 p-5">
          <h2 className="text-[14px] font-medium">Progress</h2>
          <ol className="space-y-3">
            {steps.map((step) => (
              <li key={step.label} className="flex items-start gap-2.5">
                <span
                  aria-hidden
                  className={cn("mt-1.5 size-2 shrink-0 rounded-full", step.done ? "bg-accent-solid" : "bg-muted-foreground/30")}
                />
                <span>
                  <span className="block text-[13px] font-medium">{step.label}</span>
                  <span className="block text-[12px] text-muted-foreground">{step.detail}</span>
                </span>
              </li>
            ))}
          </ol>

          {job.status === "SCHEDULED" && canWork ? (
            <Button className="w-full" disabled={busy} onClick={() => start.mutate()}>
              {start.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
              {start.isPending ? "Starting..." : "Start job"}
            </Button>
          ) : null}
          {job.status === "IN_PROGRESS" && canWork ? (
            <Button className="w-full" disabled={busy} onClick={() => complete.mutate()}>
              {complete.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CheckCircle2 className="size-4" aria-hidden />}
              {complete.isPending ? "Completing..." : "Complete job"}
            </Button>
          ) : null}

          {open && canDispatch ? (
            <>
              <Separator />
              <TechnicianPicker job={job} onAssigned={() => query.refetch()} />
              <Button
                variant="ghost"
                className="w-full text-destructive"
                disabled={busy}
                onClick={() => setCancelling(true)}
              >
                Cancel job
              </Button>
            </>
          ) : null}

          {job.status === "COMPLETED" ? (
            <p className="text-[13px] text-muted-foreground">Finished. The customer can see this in their booking history.</p>
          ) : null}
          {job.status === "CANCELLED" ? (
            <p className="text-[13px] text-muted-foreground">This job was cancelled with its booking.</p>
          ) : null}
          {!canWork && !canDispatch ? (
            <p className="rounded-md border bg-muted/30 p-2.5 text-[12px] text-muted-foreground">
              You have read-only access to this job.
            </p>
          ) : null}
        </Card>
      </div>

      <PhotoGallery jobId={job.id} canEdit={canWork && (open || job.status === "IN_PROGRESS")} canDelete={canWork && !closed} />
      <NotesPanel jobId={job.id} canWrite={canWork} canDelete={canWork} />

      {canReadHistory ? (
        <section className="space-y-3" aria-label="History">
          <h2 className="text-[15px] font-medium">History</h2>
          <Card className="p-0">
            {history.isPending ? (
              <div className="space-y-2 p-4">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ) : history.isError ? (
              <ErrorState error={history.error} onRetry={() => history.refetch()} />
            ) : (history.data?.length ?? 0) === 0 ? (
              <p className="p-4 text-[13px] text-muted-foreground">No recorded activity yet.</p>
            ) : (
              <ol className="divide-y">
                {history.data?.map((entry) => (
                  <li key={entry.id} className="flex items-center justify-between gap-4 px-4 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-medium">
                        {HISTORY_LABELS[entry.action] ?? entry.action.replaceAll("_", " ").toLowerCase()}
                      </span>
                      <span className="block truncate text-[12px] text-muted-foreground">{entry.actor_name}</span>
                    </span>
                    <time className="shrink-0 text-[12px] text-muted-foreground" dateTime={entry.created_at}>
                      {formatRelative(entry.created_at)}
                    </time>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </section>
      ) : null}

      <ConfirmDialog
        open={cancelling}
        onOpenChange={setCancelling}
        title="Cancel this job?"
        description="The job and its booking are both cancelled, and the customer is told. This can't be undone."
        confirmLabel="Cancel job"
        pendingLabel="Cancelling..."
        onConfirm={async () => {
          await cancel.mutateAsync();
        }}
      />
    </div>
  );
}
