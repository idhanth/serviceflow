"use client";

import { CalendarOff, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { EmptyState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
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
import { useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, apiFetchData } from "@/lib/api-client";
import { formatDayLabel } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Availability, AvailabilityOverride } from "@/lib/types";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function OverridesPanel({
  availability,
  canEdit,
}: {
  availability: Availability;
  canEdit: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState<AvailabilityOverride | null>(null);
  const [date, setDate] = useState(today());
  const [available, setAvailable] = useState(false);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const invalidate = [
    queryKeys.availability.all,
    queryKeys.calendar.all,
    queryKeys.bookings.all,
  ];

  const save = useResourceMutation<void, AvailabilityOverride>(
    () =>
      apiFetchData<AvailabilityOverride>(
        `employees/${availability.employee_id}/availability/overrides`,
        {
          method: "POST",
          body: JSON.stringify({
            date,
            available,
            start_time: available ? start : null,
            end_time: available ? end : null,
            reason: reason.trim() || null,
          }),
        },
      ),
    { invalidate, successMessage: "Override saved" },
  );

  const remove = useResourceMutation<AvailabilityOverride, null>(
    async (override) => {
      await apiFetch(
        `employees/${availability.employee_id}/availability/overrides/${override.id}`,
        { method: "DELETE" },
      );
      return null;
    },
    { invalidate, successMessage: "Override removed" },
  );

  function openForm() {
    setDate(today());
    setAvailable(false);
    setStart("09:00");
    setEnd("17:00");
    setReason("");
    setError(null);
    setOpen(true);
  }

  async function onSave() {
    if (available && end <= start) {
      setError("The end time has to be after the start time.");
      return;
    }
    setError(null);
    try {
      await save.mutateAsync();
      setOpen(false);
    } catch {
      // The mutation hook already surfaced the server's message.
    }
  }

  return (
    <>
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-medium">Date overrides</h2>
            <p className="text-sm text-muted-foreground">
              Time off and one-off hours. An override replaces the weekly schedule for
              that date.
            </p>
          </div>
          {canEdit ? (
            <Button variant="outline" onClick={openForm}>
              <Plus className="size-4" aria-hidden />
              Add override
            </Button>
          ) : null}
        </div>

        {availability.overrides.length === 0 ? (
          <EmptyState
            icon={CalendarOff}
            title="No upcoming overrides"
            description="The weekly schedule applies to every date until you add one."
          />
        ) : (
          <ul className="divide-y">
            {availability.overrides.map((override) => (
              <li key={override.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">
                      {formatDayLabel(`${override.date}T12:00:00Z`)}
                    </span>
                    {override.available ? (
                      <Badge
                        variant="outline"
                        className="border-blue-600/30 bg-blue-500/10 text-blue-700 dark:border-blue-400/30 dark:text-blue-300"
                      >
                        {override.start_time?.slice(0, 5)}–{override.end_time?.slice(0, 5)}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-muted text-muted-foreground">
                        Unavailable
                      </Badge>
                    )}
                  </div>
                  {override.reason ? (
                    <p className="truncate text-sm text-muted-foreground">{override.reason}</p>
                  ) : null}
                </div>
                {canEdit ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove override for ${override.date}`}
                    onClick={() => setRemoving(override)}
                  >
                    <Trash2 className="size-4 text-destructive" aria-hidden />
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add a date override</DialogTitle>
            <DialogDescription>
              Setting one replaces the normal weekly hours for that date.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {error ? (
              <p
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {error}
              </p>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="override-date">Date</Label>
              <Input
                id="override-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">What happens on this date?</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border p-3 text-sm">
                  <input
                    type="radio"
                    name="override-kind"
                    className="size-4 accent-primary"
                    checked={!available}
                    onChange={() => setAvailable(false)}
                  />
                  Not working
                </label>
                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border p-3 text-sm">
                  <input
                    type="radio"
                    name="override-kind"
                    className="size-4 accent-primary"
                    checked={available}
                    onChange={() => setAvailable(true)}
                  />
                  Different hours
                </label>
              </div>
            </fieldset>

            {available ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="override-start">From</Label>
                  <Input
                    id="override-start"
                    type="time"
                    value={start}
                    onChange={(event) => setStart(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="override-end">To</Label>
                  <Input
                    id="override-end"
                    type="time"
                    value={end}
                    onChange={(event) => setEnd(event.target.value)}
                  />
                </div>
              </div>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="override-reason">Reason (optional)</Label>
              <Input
                id="override-reason"
                maxLength={200}
                placeholder="Vacation, training, covering a late finish..."
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={save.isPending}>
              Cancel
            </Button>
            <Button onClick={onSave} disabled={save.isPending}>
              {save.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Saving...
                </>
              ) : (
                "Save override"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(next) => !next && setRemoving(null)}
        title="Remove this override?"
        description="The normal weekly schedule will apply to that date again."
        confirmLabel="Remove override"
        pendingLabel="Removing..."
        onConfirm={async () => {
          if (removing) await remove.mutateAsync(removing);
        }}
      />
    </>
  );
}
