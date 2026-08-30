"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Car, Loader2, Mail, Phone, User } from "lucide-react";
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
import { queryKeys } from "@/lib/query-keys";
import type { AssignableEmployee, Booking } from "@/lib/types";
import { cn } from "@/lib/utils";

export function BookingReviewSheet({
  booking,
  timeZone,
  onOpenChange,
}: {
  booking: Booking | null;
  timeZone: string;
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
    enabled: Boolean(booking) && booking?.status === "PENDING",
  });

  const invalidate = [queryKeys.bookings.all, queryKeys.jobs.all];

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

  const isPending = booking?.status === "PENDING";
  const canCancel = booking?.status === "PENDING" || booking?.status === "CONFIRMED";
  const jobStarted = Boolean(booking?.job && booking.job.status !== "ASSIGNED");

  return (
    <>
      <Sheet open={booking !== null} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
          {booking ? (
            <>
              <SheetHeader>
                <SheetTitle className="flex flex-wrap items-center gap-2">
                  {booking.service.name}
                  <BookingStatusBadge status={booking.status} />
                </SheetTitle>
                <SheetDescription>
                  {formatWindow(booking.requested_start, booking.requested_end, timeZone)}
                </SheetDescription>
              </SheetHeader>

              <div className="space-y-6 px-4 pb-8">
                <section className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Customer
                    </p>
                    <p className="flex items-center gap-2 text-sm font-medium">
                      <User className="size-4 text-muted-foreground" aria-hidden />
                      {booking.customer?.full_name ?? "—"}
                    </p>
                    {booking.customer ? (
                      <>
                        <a
                          href={`mailto:${booking.customer.email}`}
                          className="flex items-center gap-2 text-sm text-muted-foreground hover:underline"
                        >
                          <Mail className="size-3.5" aria-hidden />
                          {booking.customer.email}
                        </a>
                        {booking.customer.phone ? (
                          <a
                            href={`tel:${booking.customer.phone}`}
                            className="flex items-center gap-2 text-sm text-muted-foreground hover:underline"
                          >
                            <Phone className="size-3.5" aria-hidden />
                            {booking.customer.phone}
                          </a>
                        ) : null}
                      </>
                    ) : null}
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Vehicle
                    </p>
                    <p className="flex items-center gap-2 text-sm font-medium">
                      <Car className="size-4 text-muted-foreground" aria-hidden />
                      {booking.vehicle.display_name}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {[booking.vehicle.color, booking.vehicle.license_plate]
                        .filter(Boolean)
                        .join(" · ") || "No colour or plate on file"}
                    </p>
                  </div>
                </section>

                <section className="rounded-lg bg-muted/60 p-3 text-sm">
                  <span className="font-medium">{formatPrice(booking.service.base_price)}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    · {formatDuration(booking.service.duration_minutes)}
                  </span>
                </section>

                {booking.customer_notes ? (
                  <section className="space-y-1.5">
                    <h3 className="text-xs uppercase tracking-wide text-muted-foreground">
                      Customer note
                    </h3>
                    <p className="whitespace-pre-wrap rounded-lg border p-3 text-sm">
                      {booking.customer_notes}
                    </p>
                  </section>
                ) : null}

                {booking.job ? (
                  <section className="space-y-2">
                    <h3 className="text-xs uppercase tracking-wide text-muted-foreground">
                      Assigned job
                    </h3>
                    <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
                      <div>
                        <p className="text-sm font-medium">{booking.job.employee_name}</p>
                        <p className="text-sm text-muted-foreground">
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
                      <p className="flex items-start gap-2 rounded-lg border border-amber-600/30 bg-amber-500/10 p-3 text-sm">
                        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                        Nobody on the team is currently qualified for{" "}
                        {booking.service.name}. Assign the service to an employee first, then
                        confirm.
                      </p>
                    ) : null}

                    <div className="space-y-2">
                      {(candidates.data?.data ?? []).map((candidate) => (
                        <label
                          key={candidate.id}
                          className={cn(
                            "flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors duration-150 hover:bg-accent/50",
                            employeeId === candidate.id && "border-primary/50 bg-primary/5",
                          )}
                        >
                          <input
                            type="radio"
                            name="assignee"
                            className="size-4 accent-primary"
                            checked={employeeId === candidate.id}
                            onChange={() => setEmployeeId(candidate.id)}
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">
                              {candidate.full_name}
                            </span>
                            <span className="block truncate text-sm text-muted-foreground">
                              {candidate.job_title}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </section>
                ) : null}

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

                {booking.status === "CONFIRMED" && !jobStarted ? (
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
