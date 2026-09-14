"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, ApiError, apiFetchData } from "@/lib/api-client";
import { formatDuration, formatPrice, formatWindow } from "@/lib/format";
import { OPERATIONS_KEYS, queryKeys } from "@/lib/query-keys";
import type { AssignableEmployee, Booking } from "@/lib/types";
import { cn } from "@/lib/utils";

export function BookingReviewSheet({
  booking,
  timeZone,
  canWrite,
  onOpenChange,
}: {
  booking: Booking | null;
  timeZone: string;
  canWrite: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [adminNotes, setAdminNotes] = useState("");
  const [newSlot, setNewSlot] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [loadedBookingId, setLoadedBookingId] = useState<string | null>(null);

  // Reset the form when a different booking is opened - adjusted during render
  // rather than in an effect. Keyed on the id alone so a background refetch of
  // the same booking never overwrites what the admin is typing.
  if (booking && booking.id !== loadedBookingId) {
    setLoadedBookingId(booking.id);
    setEmployeeId(null);
    setAdminNotes(booking.admin_notes ?? "");
    setNewSlot("");
  }

  const candidates = useQuery<{ data: AssignableEmployee[] }, ApiError>({
    queryKey: queryKeys.bookings.assignable(booking?.id ?? "none"),
    queryFn: () =>
      apiFetch<{ data: AssignableEmployee[] }>(`bookings/${booking!.id}/assignable-employees`),
    enabled: canWrite && Boolean(booking) && booking?.status === "PENDING",
  });

  const invalidate = OPERATIONS_KEYS;

  const confirm = useResourceMutation<string, Booking>(
    (chosen) =>
      apiFetchData<Booking>(`bookings/${booking!.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({
          employee_id: chosen,
          admin_notes: adminNotes.trim() || null,
        }),
      }),
    {
      invalidate,
      successMessage: (result) =>
        `Confirmed — ${result.job?.employee_name ?? "a technician"} is assigned`,
    },
  );

  const reject = useResourceMutation<void, Booking>(
    () =>
      apiFetchData<Booking>(`bookings/${booking!.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ admin_notes: adminNotes.trim() || null }),
      }),
    { invalidate, successMessage: "Booking declined" },
  );

  const cancel = useResourceMutation<void, Booking>(
    () =>
      apiFetchData<Booking>(`bookings/${booking!.id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: adminNotes.trim() || null }),
      }),
    { invalidate, successMessage: "Booking cancelled" },
  );

  const reschedule = useResourceMutation<string, Booking>(
    (slot) =>
      apiFetchData<Booking>(`bookings/${booking!.id}/reschedule`, {
        method: "POST",
        body: JSON.stringify({ requested_start: new Date(slot).toISOString() }),
      }),
    { invalidate, successMessage: "Booking moved" },
  );

  const busy =
    confirm.isPending || reject.isPending || cancel.isPending || reschedule.isPending;

  async function onConfirm() {
    if (!employeeId) return;
    try {
      await confirm.mutateAsync(employeeId);
      onOpenChange(false);
    } catch {
      // The hook surfaced the server's message; keep the sheet open to retry.
    }
  }

  const isPending = canWrite && booking?.status === "PENDING";
  const canCancel = canWrite && (booking?.status === "PENDING" || booking?.status === "CONFIRMED");
  const jobStarted = Boolean(
    booking?.job && (booking.job.status === "IN_PROGRESS" || booking.job.status === "COMPLETED"),
  );

  return (
    <>
      <Sheet open={booking !== null} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          {booking ? (
            <>
              <SheetHeader>
                <SheetTitle className="flex flex-wrap items-center gap-2.5 text-[16px]">
                  {booking.service.name}
                  <BookingStatusBadge status={booking.status} variant="chip" />
                </SheetTitle>
                <SheetDescription>
                  {formatWindow(booking.requested_start, booking.requested_end, timeZone)}
                </SheetDescription>
              </SheetHeader>

              <div className="space-y-5 px-4 pb-8">
                {/* Facts first, as a definition list. Two aligned columns with
                    real gaps - the previous grid let the customer's email run
                    into the address. */}
                <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
                  <div className="min-w-0 space-y-1">
                    <dt className="text-[12px] text-muted-foreground">Customer</dt>
                    <dd className="space-y-0.5">
                      <p className="text-[13px] font-medium">
                        {booking.customer?.full_name ?? "—"}
                      </p>
                      {booking.customer ? (
                        <>
                          <a
                            href={`mailto:${booking.customer.email}`}
                            className="focus-ring block break-all text-[13px] text-muted-foreground hover:text-foreground hover:underline"
                          >
                            {booking.customer.email}
                          </a>
                          {booking.customer.phone ? (
                            <a
                              href={`tel:${booking.customer.phone}`}
                              className="focus-ring block truncate text-[13px] tabular-nums text-muted-foreground hover:text-foreground hover:underline"
                            >
                              {booking.customer.phone}
                            </a>
                          ) : null}
                        </>
                      ) : null}
                    </dd>
                  </div>

                  <div className="min-w-0 space-y-1">
                    <dt className="text-[12px] text-muted-foreground">Service address</dt>
                    <dd className="text-[13px] font-medium">
                      {booking.customer?.address ?? "No address on file"}
                    </dd>
                  </div>

                  <div className="space-y-1">
                    <dt className="text-[12px] text-muted-foreground">Price</dt>
                    <dd className="text-[13px] font-medium tabular-nums">
                      {formatPrice(booking.service.base_price)}
                    </dd>
                  </div>

                  <div className="space-y-1">
                    <dt className="text-[12px] text-muted-foreground">Duration</dt>
                    <dd className="text-[13px] font-medium tabular-nums">
                      {formatDuration(booking.service.duration_minutes)}
                    </dd>
                  </div>
                </dl>

                {booking.customer_notes ? (
                  <section className="space-y-1.5">
                    <h3 className="text-[13px] font-medium">Note from the customer</h3>
                    {/* A quotation, not a form field: a bordered box here reads
                        as something you are meant to type into. */}
                    <p className="whitespace-pre-wrap border-l-2 border-border pl-3 text-[13px] text-muted-foreground">
                      {booking.customer_notes}
                    </p>
                  </section>
                ) : null}

                {booking.job?.employee_name ? (
                  <section className="space-y-1.5">
                    <h3 className="text-[13px] font-medium">Assigned</h3>
                    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium">
                          {booking.job.employee_name}
                        </p>
                        <p className="truncate text-[12px] text-muted-foreground">
                          {formatWindow(
                            booking.job.scheduled_start,
                            booking.job.scheduled_end,
                            timeZone,
                          )}
                        </p>
                      </div>
                      <JobStatusBadge status={booking.job.status} />
                    </div>
                  </section>
                ) : null}

                <Separator />

                {isPending ? (
                  <section className="space-y-3">
                    <h3 className="text-sm font-medium">Assign a technician</h3>

                    {candidates.isPending ? (
                      <div className="space-y-2">
                        {[0, 1].map((index) => (
                          <Skeleton key={index} className="h-14 w-full rounded-lg" />
                        ))}
                      </div>
                    ) : null}

                    {candidates.isError ? (
                      <ErrorState
                        error={candidates.error}
                        onRetry={() => candidates.refetch()}
                      />
                    ) : null}

                    {candidates.isSuccess && candidates.data.data.length === 0 ? (
                      <p className="flex items-start gap-2 rounded-md border border-status-pending/25 bg-status-pending/10 p-2.5 text-[13px]">
                        <AlertCircle
                          className="mt-px size-3.5 shrink-0 text-status-pending"
                          aria-hidden
                        />
                        Nobody on the team is qualified for {booking.service.name} yet. Assign
                        the service to someone first, then confirm.
                      </p>
                    ) : null}

                    {candidates.isSuccess &&
                    candidates.data.data.length > 0 &&
                    !candidates.data.data.some((c) => c.assignable) ? (
                      <p className="flex items-start gap-2 rounded-md border border-status-pending/25 bg-status-pending/10 p-2.5 text-[13px]">
                        <AlertCircle
                          className="mt-px size-3.5 shrink-0 text-status-pending"
                          aria-hidden
                        />
                        Everyone qualified is off or already booked then. Reschedule the
                        booking, or adjust someone&apos;s availability.
                      </p>
                    ) : null}

                    <p className="text-[12px] text-muted-foreground">
                      Ranked by who is free, then by how light their day already is.
                    </p>

                    {/* One bordered list, not one card per person: this is a
                        chooser, and eight bordered boxes inside a panel inside a
                        sheet is three frames too many. */}
                    <div className="divide-y overflow-hidden rounded-md border">
                      {(candidates.data?.data ?? []).map((candidate, index) => (
                        <label
                          key={candidate.id}
                          className={cn(
                            "flex items-start gap-3 px-3 py-2.5 transition-colors duration-75",
                            candidate.assignable
                              ? "cursor-pointer hover:bg-muted/50"
                              : "cursor-not-allowed",
                            employeeId === candidate.id && "bg-accent-solid/[0.07]",
                          )}
                        >
                          <input
                            type="radio"
                            name="assignee"
                            className="mt-1 size-3.5 accent-[var(--accent-solid)]"
                            checked={employeeId === candidate.id}
                            disabled={!candidate.assignable}
                            onChange={() => setEmployeeId(candidate.id)}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <span
                                className={cn(
                                  "truncate text-[13px] font-medium",
                                  !candidate.assignable && "text-muted-foreground",
                                )}
                              >
                                {candidate.full_name}
                              </span>
                              <span className="truncate text-[12px] text-muted-foreground">
                                {candidate.job_title}
                              </span>
                              {index === 0 && candidate.assignable ? (
                                <span className="rounded border border-status-done/25 bg-status-done/10 px-1 py-px text-[11px] font-medium text-status-done">
                                  Best fit
                                </span>
                              ) : null}
                              {!candidate.assignable ? (
                                <span className="text-[11px] font-medium text-muted-foreground">
                                  {candidate.conflict ? "Busy" : "Unavailable"}
                                </span>
                              ) : null}
                            </span>
                            {/* The evidence behind the ranking, so it is explained
                                rather than asserted. */}
                            <span className="mt-0.5 block text-[12px] text-muted-foreground">
                              {candidate.reason ??
                                `${candidate.jobs_today} ${
                                  candidate.jobs_today === 1 ? "job" : "jobs"
                                } that day · ${formatDuration(
                                  candidate.scheduled_minutes_today,
                                )} scheduled`}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </section>
                ) : null}

                {canWrite ? (
                <section className="space-y-2">
                  <Label htmlFor="admin-notes">Internal notes</Label>
                  <Textarea
                    id="admin-notes"
                    rows={3}
                    maxLength={2000}
                    value={adminNotes}
                    onChange={(event) => setAdminNotes(event.target.value)}
                    placeholder="Only your team sees this."
                  />
                </section>
                ) : booking.admin_notes ? (
                  <section className="space-y-1.5">
                    <h3 className="text-[13px] font-medium">Internal notes</h3>
                    <p className="whitespace-pre-wrap border-l-2 border-border pl-3 text-[13px] text-muted-foreground">
                      {booking.admin_notes}
                    </p>
                  </section>
                ) : null}

                {canWrite && booking.status === "CONFIRMED" && !jobStarted ? (
                  <section className="space-y-2">
                    <Label htmlFor="reschedule-slot">Move to a new time</Label>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input
                        id="reschedule-slot"
                        type="datetime-local"
                        value={newSlot}
                        onChange={(event) => setNewSlot(event.target.value)}
                      />
                      <Button
                        variant="outline"
                        disabled={!newSlot || busy}
                        onClick={() => reschedule.mutate(newSlot)}
                      >
                        {reschedule.isPending ? (
                          <>
                            <Loader2 className="size-4 animate-spin" aria-hidden />
                            Moving...
                          </>
                        ) : (
                          "Reschedule"
                        )}
                      </Button>
                    </div>
                  </section>
                ) : null}

                <div className="flex flex-wrap gap-2 pt-2">
                  {isPending ? (
                    <>
                      <Button onClick={onConfirm} disabled={!employeeId || busy}>
                        {confirm.isPending ? (
                          <>
                            <Loader2 className="size-4 animate-spin" aria-hidden />
                            Confirming...
                          </>
                        ) : (
                          "Confirm booking"
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => setRejecting(true)}
                      >
                        Decline
                      </Button>
                    </>
                  ) : null}

                  {canCancel && !jobStarted ? (
                    <Button
                      variant="ghost"
                      className="text-destructive"
                      disabled={busy}
                      onClick={() => setCancelling(true)}
                    >
                      Cancel booking
                    </Button>
                  ) : null}
                </div>

                {!canWrite ? (
                  <p className="rounded-md border bg-muted/30 p-2.5 text-[12px] text-muted-foreground">
                    You have read-only access to bookings.
                  </p>
                ) : null}

                {jobStarted ? (
                  <p className="text-sm text-muted-foreground">
                    Work has already started, so this booking can no longer be moved or
                    cancelled.
                  </p>
                ) : null}
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={rejecting}
        onOpenChange={setRejecting}
        title="Decline this booking?"
        description="The customer will see the request as declined. This cannot be undone — they'd need to book again."
        confirmLabel="Decline booking"
        pendingLabel="Declining..."
        onConfirm={async () => {
          await reject.mutateAsync();
          onOpenChange(false);
        }}
      />

      <ConfirmDialog
        open={cancelling}
        onOpenChange={setCancelling}
        title="Cancel this booking?"
        description="The appointment is cancelled and any assigned job is cancelled with it. This cannot be undone."
        confirmLabel="Cancel booking"
        pendingLabel="Cancelling..."
        onConfirm={async () => {
          await cancel.mutateAsync();
          onOpenChange(false);
        }}
      />
    </>
  );
}
