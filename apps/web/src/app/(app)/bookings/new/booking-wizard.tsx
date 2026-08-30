"use client";

import { ArrowLeft, Car, Check, Clock, Loader2, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetchData, newIdempotencyKey } from "@/lib/api-client";
import { formatDuration, formatPrice, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking, Service, Vehicle } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = ["Service", "Vehicle", "Date & time", "Review"] as const;

/** Local datetime string ("2026-09-05T10:00") -> an ISO string with this browser's offset. */
function toIsoWithOffset(local: string): string {
  return new Date(local).toISOString();
}

/** A short, stable stamp of the payload. Only has to change when the payload does. */
function fingerprint(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function minimumSlot(): string {
  const soonest = new Date(Date.now() + 60 * 60 * 1000);
  soonest.setMinutes(soonest.getMinutes() - soonest.getTimezoneOffset());
  return soonest.toISOString().slice(0, 16);
}

export function BookingWizard() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [serviceId, setServiceId] = useState<string | null>(null);
  const [vehicleId, setVehicleId] = useState<string | null>(null);
  const [slot, setSlot] = useState("");
  const [notes, setNotes] = useState("");
  const [slotError, setSlotError] = useState<string | null>(null);

  const serviceParams = { active: true, page_size: 50 };
  const services = usePagedResource<Service>(
    queryKeys.services.list(serviceParams),
    "services",
    serviceParams,
  );
  const vehicleParams = { page_size: 50 };
  const vehicles = usePagedResource<Vehicle>(
    queryKeys.vehicles.list(vehicleParams),
    "vehicles",
    vehicleParams,
  );

  const service = useMemo(
    () => services.data?.data.find((item) => item.id === serviceId) ?? null,
    [services.data, serviceId],
  );
  const vehicle = useMemo(
    () => vehicles.data?.data.find((item) => item.id === vehicleId) ?? null,
    [vehicles.data, vehicleId],
  );

  // The API computes the real end time; this is the same arithmetic, for preview only.
  const previewEnd = useMemo(() => {
    if (!service || !slot) return null;
    const end = new Date(slot);
    end.setMinutes(end.getMinutes() + service.duration_minutes);
    return end.toISOString();
  }, [service, slot]);

  // One key per version of the booking the user is trying to make. Retrying the
  // same booking - a double click, a dropped response, a refresh - reuses it and
  // the server replays the original instead of creating a second appointment.
  // Editing any field makes it a different booking, so the key changes with the
  // payload; the mount nonce keeps two wizards from colliding on one key.
  const [nonce] = useState(newIdempotencyKey);
  const idempotencyKey = useMemo(
    () => `${nonce}-${fingerprint([serviceId, vehicleId, slot, notes.trim()].join("|"))}`,
    [nonce, serviceId, vehicleId, slot, notes],
  );

  const submit = useResourceMutation<void, Booking>(
    () =>
      apiFetchData<Booking>("bookings", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          service_id: serviceId,
          vehicle_id: vehicleId,
          requested_start: toIsoWithOffset(slot),
          customer_notes: notes.trim() || null,
        }),
      }),
    {
      invalidate: [queryKeys.bookings.all],
      successMessage: "Booking requested — we'll confirm shortly",
    },
  );

  async function onSubmit() {
    try {
      await submit.mutateAsync();
      router.push("/bookings");
      router.refresh();
    } catch {
      // The mutation hook already surfaced the server's message as a toast.
    }
  }

  function goToDateStep() {
    setSlotError(null);
    setStep(2);
  }

  function confirmSlot() {
    if (!slot) {
      setSlotError("Choose a date and time.");
      return;
    }
    if (new Date(slot).getTime() <= Date.now()) {
      setSlotError("Choose a time in the future.");
      return;
    }
    setSlotError(null);
    setStep(3);
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Button variant="ghost" size="sm" className="-ml-2" onClick={() => router.push("/bookings")}>
          <ArrowLeft className="size-4" aria-hidden />
          Back to bookings
        </Button>
        <h1 className="text-2xl font-semibold tracking-tight">Book a service</h1>
      </div>

      <ol className="flex flex-wrap gap-2" aria-label="Progress">
        {STEPS.map((label, index) => (
          <li key={label}>
            <span
              aria-current={index === step ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors duration-150",
                index === step && "border-primary/40 bg-primary/5 font-medium",
                index < step && "text-muted-foreground",
                index > step && "text-muted-foreground/70",
              )}
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-full text-xs",
                  index < step ? "bg-primary text-primary-foreground" : "bg-muted",
                )}
              >
                {index < step ? <Check className="size-3" aria-hidden /> : index + 1}
              </span>
              {label}
            </span>
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <section aria-label="Choose a service" className="space-y-4">
          {services.isPending ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <CardSkeletons count={4} />
            </div>
          ) : null}
          {services.isError ? (
            <Card>
              <ErrorState error={services.error} onRetry={() => services.refetch()} />
            </Card>
          ) : null}
          {services.isSuccess && services.data.data.length === 0 ? (
            <Card>
              <EmptyState
                icon={Sparkles}
                title="No services available"
                description="This business hasn't published any bookable services yet."
              />
            </Card>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            {(services.data?.data ?? []).map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  setServiceId(option.id);
                  setStep(1);
                }}
                className={cn(
                  "rounded-xl border bg-card p-5 text-left transition-colors duration-150 hover:border-primary/40 hover:bg-accent/40",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  serviceId === option.id && "border-primary/50 bg-primary/5",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-medium">{option.name}</h2>
                  <span className="shrink-0 font-medium tabular-nums">
                    {formatPrice(option.base_price)}
                  </span>
                </div>
                {option.description ? (
                  <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">
                    {option.description}
                  </p>
                ) : null}
                <p className="mt-3 flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Clock className="size-3.5" aria-hidden />
                  {formatDuration(option.duration_minutes)}
                </p>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {step === 1 ? (
        <section aria-label="Choose a vehicle" className="space-y-4">
          {vehicles.isPending ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <CardSkeletons count={2} />
            </div>
          ) : null}
          {vehicles.isError ? (
            <Card>
              <ErrorState error={vehicles.error} onRetry={() => vehicles.refetch()} />
            </Card>
          ) : null}
          {vehicles.isSuccess && vehicles.data.data.length === 0 ? (
            <Card>
              <EmptyState
                icon={Car}
                title="No vehicles yet"
                description="Add a vehicle first so we know what we'll be working on."
                action={
                  <Button size="sm" onClick={() => router.push("/vehicles")}>
                    Add a vehicle
                  </Button>
                }
              />
            </Card>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            {(vehicles.data?.data ?? []).map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  setVehicleId(option.id);
                  goToDateStep();
                }}
                className={cn(
                  "flex items-center gap-3 rounded-xl border bg-card p-5 text-left transition-colors duration-150 hover:border-primary/40 hover:bg-accent/40",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  vehicleId === option.id && "border-primary/50 bg-primary/5",
                )}
              >
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <Car className="size-5 text-muted-foreground" aria-hidden />
                </div>
                <div className="min-w-0">
                  <p className="truncate font-medium">{option.display_name}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {[option.color, option.license_plate].filter(Boolean).join(" · ") || "—"}
                  </p>
                </div>
              </button>
            ))}
          </div>

          <Button variant="outline" onClick={() => setStep(0)}>
            Back
          </Button>
        </section>
      ) : null}

      {step === 2 ? (
        <section aria-label="Choose a date and time" className="space-y-4">
          <Card className="space-y-4 p-5">
            <div className="space-y-2">
              <Label htmlFor="slot">Preferred date and time</Label>
              <Input
                id="slot"
                type="datetime-local"
                min={minimumSlot()}
                value={slot}
                aria-invalid={Boolean(slotError)}
                aria-describedby={slotError ? "slot-error" : "slot-help"}
                onChange={(event) => {
                  setSlot(event.target.value);
                  setSlotError(null);
                }}
              />
              {slotError ? (
                <p id="slot-error" className="text-sm text-destructive">
                  {slotError}
                </p>
              ) : (
                <p id="slot-help" className="text-sm text-muted-foreground">
                  {service
                    ? `${service.name} takes about ${formatDuration(service.duration_minutes)}.`
                    : null}
                  {previewEnd ? ` Expected to finish around ${formatTime(previewEnd)}.` : null}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">Anything we should know? (optional)</Label>
              <Textarea
                id="notes"
                rows={3}
                maxLength={2000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Pet hair in the back, water spots on the hood..."
              />
            </div>
          </Card>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={confirmSlot}>Review</Button>
          </div>
        </section>
      ) : null}

      {step === 3 && service && vehicle ? (
        <section aria-label="Review and submit" className="space-y-4">
          <Card className="divide-y p-0">
            <dl className="grid gap-3 p-5 sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Service</dt>
                <dd className="mt-1 font-medium">{service.name}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">Vehicle</dt>
                <dd className="mt-1 font-medium">{vehicle.display_name}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  Requested time
                </dt>
                <dd className="mt-1 font-medium">
                  {new Date(slot).toLocaleString("en-US", {
                    weekday: "short",
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  Estimated
                </dt>
                <dd className="mt-1 font-medium">
                  {formatPrice(service.base_price)} ·{" "}
                  {formatDuration(service.duration_minutes)}
                </dd>
              </div>
            </dl>
            {notes.trim() ? (
              <div className="p-5">
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  Your notes
                </dt>
                <dd className="mt-1 whitespace-pre-wrap text-sm">{notes}</dd>
              </div>
            ) : null}
          </Card>

          <p className="text-sm text-muted-foreground">
            We&apos;ll review your request and confirm a technician. You can cancel any time
            before then.
          </p>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setStep(2)} disabled={submit.isPending}>
              Back
            </Button>
            <Button onClick={onSubmit} disabled={submit.isPending}>
              {submit.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Submitting...
                </>
              ) : (
                "Request booking"
              )}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
