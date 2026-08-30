"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Car, CheckCircle2, Loader2, Mail, Phone, Play, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { JobStatusBadge } from "@/components/data/status-badge";
import { ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, ApiError, apiFetchData } from "@/lib/api-client";
import { formatDuration, formatPrice, formatTime, formatWindow } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Job } from "@/lib/types";

export function JobDetailClient({ jobId, timeZone }: { jobId: string; timeZone: string }) {
  const [notes, setNotes] = useState("");
  const [notesReady, setNotesReady] = useState(false);

  const query = useQuery<{ data: Job }, ApiError>({
    queryKey: queryKeys.jobs.detail(jobId),
    queryFn: () => apiFetch<{ data: Job }>(`jobs/${jobId}`),
  });

  const job = query.data?.data;

  // Seed the notes box once, without an effect that would fight the user's typing.
  if (job && !notesReady) {
    setNotes(job.internal_notes ?? "");
    setNotesReady(true);
  }

  const invalidate = [queryKeys.jobs.all, queryKeys.bookings.all];

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

  const busy = start.isPending || complete.isPending;

  if (query.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Card className="space-y-4 p-5">
          <Skeleton className="h-6 w-2/5" />
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-24 w-full" />
        </Card>
      </div>
    );
  }

  if (query.isError || !job) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/jobs" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back to jobs
        </Button>
        <Card>
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/jobs" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back to jobs
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{job.service.name}</h1>
          <JobStatusBadge status={job.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {formatWindow(job.scheduled_start, job.scheduled_end, timeZone)} ·{" "}
          {formatDuration(job.service.duration_minutes)} ·{" "}
          {formatPrice(job.service.base_price)}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="space-y-4 p-5 lg:col-span-2">
          <section className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <h2 className="text-xs uppercase tracking-wide text-muted-foreground">Customer</h2>
              <p className="flex items-center gap-2 font-medium">
                <User className="size-4 text-muted-foreground" aria-hidden />
                {job.customer.full_name}
              </p>
              <a
                href={`mailto:${job.customer.email}`}
                className="flex items-center gap-2 text-sm text-muted-foreground hover:underline"
              >
                <Mail className="size-3.5" aria-hidden />
                {job.customer.email}
              </a>
              {job.customer.phone ? (
                <a
                  href={`tel:${job.customer.phone}`}
                  className="flex items-center gap-2 text-sm text-muted-foreground hover:underline"
                >
                  <Phone className="size-3.5" aria-hidden />
                  {job.customer.phone}
                </a>
              ) : null}
            </div>

            <div className="space-y-1">
              <h2 className="text-xs uppercase tracking-wide text-muted-foreground">Vehicle</h2>
              <p className="flex items-center gap-2 font-medium">
                <Car className="size-4 text-muted-foreground" aria-hidden />
                {job.vehicle.display_name}
              </p>
              <p className="text-sm text-muted-foreground">
                {[job.vehicle.color, job.vehicle.license_plate].filter(Boolean).join(" · ") ||
                  "No colour or plate on file"}
              </p>
            </div>
          </section>

          {job.customer_notes ? (
            <>
              <Separator />
              <section className="space-y-1.5">
                <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
                  What the customer asked for
                </h2>
                <p className="whitespace-pre-wrap rounded-lg border p-3 text-sm">
                  {job.customer_notes}
                </p>
              </section>
            </>
          ) : null}

          <Separator />

          <section className="space-y-2">
            <Label htmlFor="internal-notes">Internal notes</Label>
            <Textarea
              id="internal-notes"
              rows={4}
              maxLength={2000}
              value={notes}
              disabled={job.status === "COMPLETED" || job.status === "CANCELLED"}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Saved when you complete the job. The customer never sees this."
            />
          </section>
        </Card>

        <Card className="h-fit space-y-4 p-5">
          <h2 className="text-sm font-medium">Progress</h2>

          <ol className="space-y-3 text-sm">
            <li className="flex items-start gap-2.5">
              <span className="mt-1 size-2 shrink-0 rounded-full bg-primary" aria-hidden />
              <span>
                <span className="block font-medium">Assigned</span>
                <span className="block text-muted-foreground">
                  to {job.employee.full_name}
                </span>
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <span
                aria-hidden
                className={`mt-1 size-2 shrink-0 rounded-full ${
                  job.started_at ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              />
              <span>
                <span className="block font-medium">Started</span>
                <span className="block text-muted-foreground">
                  {job.started_at ? formatTime(job.started_at, timeZone) : "Not yet"}
                </span>
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <span
                aria-hidden
                className={`mt-1 size-2 shrink-0 rounded-full ${
                  job.completed_at ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              />
              <span>
                <span className="block font-medium">Completed</span>
                <span className="block text-muted-foreground">
                  {job.completed_at ? formatTime(job.completed_at, timeZone) : "Not yet"}
                </span>
              </span>
            </li>
          </ol>

          <Separator />

          {job.status === "ASSIGNED" ? (
            <Button className="w-full" disabled={busy} onClick={() => start.mutate()}>
              {start.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Starting...
                </>
              ) : (
                <>
                  <Play className="size-4" aria-hidden />
                  Start job
                </>
              )}
            </Button>
          ) : null}

          {job.status === "IN_PROGRESS" ? (
            <Button className="w-full" disabled={busy} onClick={() => complete.mutate()}>
              {complete.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Completing...
                </>
              ) : (
                <>
                  <CheckCircle2 className="size-4" aria-hidden />
                  Complete job
                </>
              )}
            </Button>
          ) : null}

          {job.status === "COMPLETED" ? (
            <p className="rounded-lg border border-emerald-600/30 bg-emerald-500/10 p-3 text-sm">
              This job is finished. The customer can see it in their booking history.
            </p>
          ) : null}

          {job.status === "CANCELLED" ? (
            <p className="rounded-lg border p-3 text-sm text-muted-foreground">
              This job was cancelled.
            </p>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
