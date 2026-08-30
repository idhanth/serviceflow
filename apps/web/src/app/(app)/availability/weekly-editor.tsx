"use client";

import { Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Availability, WeeklyWindowInput } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Monday-first, matching the API's Monday-0 numbering. */
const DAYS = [
  { value: 0, label: "Monday", short: "Mon" },
  { value: 1, label: "Tuesday", short: "Tue" },
  { value: 2, label: "Wednesday", short: "Wed" },
  { value: 3, label: "Thursday", short: "Thu" },
  { value: 4, label: "Friday", short: "Fri" },
  { value: 5, label: "Saturday", short: "Sat" },
  { value: 6, label: "Sunday", short: "Sun" },
] as const;

const DEFAULT_SHIFT = { start: "09:00", end: "17:00" };

type Draft = Record<number, { start: string; end: string }[]>;

function toDraft(weekly: Availability["weekly"]): Draft {
  const draft: Draft = {};
  for (const day of DAYS) draft[day.value] = [];
  for (const window of weekly) {
    draft[window.day_of_week]?.push({
      start: window.start_time.slice(0, 5),
      end: window.end_time.slice(0, 5),
    });
  }
  return draft;
}

function overlapsWithin(shifts: { start: string; end: string }[]): boolean {
  const ordered = [...shifts].sort((a, b) => a.start.localeCompare(b.start));
  return ordered.some((shift, index) => index > 0 && shift.start < ordered[index - 1].end);
}

export function WeeklyEditor({
  availability,
  canEdit,
}: {
  availability: Availability;
  canEdit: boolean;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(availability.weekly));
  const [loadedFor, setLoadedFor] = useState(availability.employee_id);
  const [error, setError] = useState<string | null>(null);

  // Re-seed when the admin switches to a different employee. Adjusted during
  // render rather than in an effect, so unsaved edits are not clobbered by a
  // background refetch of the same person.
  if (availability.employee_id !== loadedFor) {
    setLoadedFor(availability.employee_id);
    setDraft(toDraft(availability.weekly));
    setError(null);
  }

  const save = useResourceMutation<WeeklyWindowInput[], Availability>(
    (windows) =>
      apiFetchData<Availability>(`employees/${availability.employee_id}/availability`, {
        method: "PUT",
        body: JSON.stringify({ windows }),
      }),
    {
      invalidate: [queryKeys.availability.all, queryKeys.calendar.all, queryKeys.bookings.all],
      successMessage: "Weekly schedule saved",
    },
  );

  function update(day: number, index: number, field: "start" | "end", value: string) {
    setError(null);
    setDraft((current) => {
      const shifts = [...(current[day] ?? [])];
      shifts[index] = { ...shifts[index], [field]: value };
      return { ...current, [day]: shifts };
    });
  }

  function addShift(day: number) {
    setError(null);
    setDraft((current) => ({ ...current, [day]: [...(current[day] ?? []), { ...DEFAULT_SHIFT }] }));
  }

  function removeShift(day: number, index: number) {
    setError(null);
    setDraft((current) => ({
      ...current,
      [day]: (current[day] ?? []).filter((_, i) => i !== index),
    }));
  }

  function onSave() {
    for (const day of DAYS) {
      const shifts = draft[day.value] ?? [];
      if (shifts.some((shift) => shift.end <= shift.start)) {
        setError(`${day.label}: each shift has to end after it starts.`);
        return;
      }
      if (overlapsWithin(shifts)) {
        setError(`${day.label}: two shifts overlap.`);
        return;
      }
    }
    setError(null);
    save.mutate(
      DAYS.flatMap((day) =>
        (draft[day.value] ?? []).map((shift) => ({
          day_of_week: day.value,
          start_time: shift.start,
          end_time: shift.end,
        })),
      ),
    );
  }

  const totalShifts = DAYS.reduce((sum, day) => sum + (draft[day.value]?.length ?? 0), 0);

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">Weekly schedule</h2>
          <p className="text-sm text-muted-foreground">
            Hours are local to the shop ({availability.timezone.replace("_", " ")}).
          </p>
        </div>
        {canEdit ? (
          <Button onClick={onSave} disabled={save.isPending}>
            {save.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Saving...
              </>
            ) : (
              "Save changes"
            )}
          </Button>
        ) : null}
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      {totalShifts === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          No working hours set. Until at least one shift exists, no work can be assigned.
        </p>
      ) : null}

      <ul className="divide-y">
        {DAYS.map((day) => {
          const shifts = draft[day.value] ?? [];
          return (
            <li key={day.value} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-start">
              <div className="flex w-full items-center justify-between sm:w-32 sm:pt-2">
                <span
                  className={cn(
                    "text-sm font-medium",
                    shifts.length === 0 && "text-muted-foreground",
                  )}
                >
                  {day.label}
                </span>
                {shifts.length === 0 ? (
                  <span className="text-xs text-muted-foreground sm:hidden">Off</span>
                ) : null}
              </div>

              <div className="flex-1 space-y-2">
                {shifts.length === 0 ? (
                  <p className="hidden text-sm text-muted-foreground sm:block sm:pt-2">Off</p>
                ) : null}

                {shifts.map((shift, index) => (
                  <div key={index} className="flex flex-wrap items-center gap-2">
                    <Label htmlFor={`d${day.value}-s${index}`} className="sr-only">
                      {day.label} shift {index + 1} start
                    </Label>
                    <Input
                      id={`d${day.value}-s${index}`}
                      type="time"
                      className="w-32"
                      value={shift.start}
                      disabled={!canEdit}
                      onChange={(event) => update(day.value, index, "start", event.target.value)}
                    />
                    <span className="text-muted-foreground">to</span>
                    <Label htmlFor={`d${day.value}-e${index}`} className="sr-only">
                      {day.label} shift {index + 1} end
                    </Label>
                    <Input
                      id={`d${day.value}-e${index}`}
                      type="time"
                      className="w-32"
                      value={shift.end}
                      disabled={!canEdit}
                      onChange={(event) => update(day.value, index, "end", event.target.value)}
                    />
                    {canEdit ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove ${day.label} shift ${index + 1}`}
                        onClick={() => removeShift(day.value, index)}
                      >
                        <Trash2 className="size-4 text-destructive" aria-hidden />
                      </Button>
                    ) : null}
                  </div>
                ))}

                {canEdit ? (
                  <Button variant="ghost" size="sm" onClick={() => addShift(day.value)}>
                    <Plus className="size-4" aria-hidden />
                    {shifts.length === 0 ? "Add hours" : "Add another shift"}
                  </Button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
