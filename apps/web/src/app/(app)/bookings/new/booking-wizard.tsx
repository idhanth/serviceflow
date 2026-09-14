"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, Clock, Loader2, Tags, UserRound, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { FieldSelect } from "@/components/data/field-select";
import { SearchInput } from "@/components/data/search-input";
import { CardSkeletons, EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, usePagedResource, useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, ApiError, apiFetchData, newIdempotencyKey } from "@/lib/api-client";
import { minutesToLabel, todayIn, zonedTimeToIso } from "@/lib/dates";
import { formatDuration, formatPrice, formatTime, formatWindow } from "@/lib/format";
import { OPERATIONS_KEYS, queryKeys } from "@/lib/query-keys";
import type { AssignableEmployee, Booking, Customer, Service } from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = "customer" | "service" | "time" | "review";

/** Half-hour starts across a working day, in the business's timezone. */
const TIMES = Array.from({ length: 23 }, (_, index) => 7 * 60 + index * 30);

/** A short, stable stamp of the payload. Only has to change when the payload does. */
function fingerprint(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function Choice({
  selected,
  onSelect,
  children,
  className,
  disabled,
}: {
  selected: boolean;
  onSelect: () => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "focus-ring rounded-lg border bg-surface p-3.5 text-left transition-colors duration-75",
        "hover:border-accent-solid/40 hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-60",
        selected && "border-accent-solid/60 bg-accent-solid/[0.05]",
        className,
      )}
    >
      {children}
    </button>
  );
}

/**
 * Creating a booking, one decision at a time.
 *
 *   staff:     customer -> service -> time and technician -> review
 *   customer:  service -> time and technician -> review
 *
 * The technician list is asked for the exact slot being considered, so who is
 * free - and why the others aren't - is shown before submitting rather than
 * discovered from a refusal. The server still decides: if someone else takes
 * the slot in the meantime, its conflict message is shown here, in words, with
 * a way back to choose again.
 */
export function BookingWizard({
  timeZone,
  staff,
  initialCustomerId,
}: {
  timeZone: string;
  staff: boolean;
  initialCustomerId: string | null;
}) {
  const router = useRouter();
  const steps: Step[] = staff ? ["customer", "service", "time", "review"] : ["service", "time", "review"];
  const labels: Record<Step, string> = {
    customer: "Customer",
    service: "Service",
    time: "Time & technician",
    review: "Review",
  };

  const [step, setStep] = useState<Step>(staff && !initialCustomerId ? "customer" : "service");
  const [customerQuery, setCustomerQuery] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [service, setService] = useState<Service | null>(null);
  const [date, setDate] = useState(() => todayIn(timeZone));
  const [time, setTime] = useState<number | null>(null);
  const [employeeId, setEmployeeId] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [conflict, setConflict] = useState<string | null>(null);

  const initialCustomer = useQuery<Customer, ApiError>({
    queryKey: queryKeys.customers.detail(initialCustomerId ?? "none"),
    queryFn: () => apiFetchData<Customer>(`customers/${initialCustomerId}`),
    enabled: staff && Boolean(initialCustomerId) && customer === null,
  });
  const chosenCustomer = customer ?? initialCustomer.data ?? null;

  const customerParams = { q: customerQuery, page_size: 8 };
  const customers = usePagedResource<Customer>(queryKeys.customers.list(customerParams), "customers", customerParams, {
    enabled: staff && step === "customer",
  });
  const serviceParams = { active: true, page_size: 50 };
  const services = usePagedResource<Service>(queryKeys.services.list(serviceParams), "services", serviceParams);

  const startIso = useMemo(
    () => (time === null ? null : zonedTimeToIso(`${date}T${minutesToLabelClock(time)}`, timeZone)),
    [date, time, timeZone],
  );
  // Captured once: the server re-checks the time on submit, so this only has to
  // stop an obviously past slot from being offered.
  const [openedAt] = useState(() => Date.now());
  const inPast = startIso !== null && new Date(startIso).getTime() <= openedAt;

  const candidateParams = { service_id: service?.id, start: startIso };
  const candidates = useQuery<{ data: AssignableEmployee[] }, ApiError>({
    queryKey: queryKeys.bookings.candidates(candidateParams),
    queryFn: () =>
      apiFetch<{ data: AssignableEmployee[] }>(
        `scheduling/candidates?service_id=${service!.id}&start=${encodeURIComponent(startIso!)}`,
      ),
    enabled: Boolean(service && startIso && !inPast),
  });
  const technician = candidates.data?.data.find((candidate) => candidate.id === employeeId) ?? null;

  // One key per version of the booking being made: a double click, a dropped
  // response or a refresh replays the original instead of booking twice.
  const [nonce] = useState(newIdempotencyKey);
  const idempotencyKey = `${nonce}-${fingerprint(
    [chosenCustomer?.id, service?.id, startIso, employeeId, notes.trim()].join("|"),
  )}`;

  const submit = useResourceMutation<void, Booking>(
    () =>
      apiFetchData<Booking>("bookings", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          customer_id: staff ? chosenCustomer?.id : undefined,
          service_id: service?.id,
          employee_id: employeeId || null,
          requested_start: startIso,
          customer_notes: notes.trim() || null,
        }),
      }),
    {
      invalidate: OPERATIONS_KEYS,
      successMessage: (booking) =>
        booking.status === "CONFIRMED"
          ? `Booked with ${booking.job?.employee_name ?? "a technician"}`
          : staff
            ? "Booking created - it's waiting for a technician"
            : "Booking requested - we'll confirm a technician shortly",
    },
  );

  async function onSubmit() {
    setConflict(null);
    try {
      const booking = await submit.mutateAsync();
      router.push(`/bookings/${booking.id}`);
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(errorMessage(error, "That slot is no longer available."));
        void candidates.refetch();
      }
    }
  }

  const index = steps.indexOf(step);
  const go = (next: Step) => {
    setConflict(null);
    setStep(next);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="space-y-1">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/bookings" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Bookings
        </Button>
        <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">
          {staff ? "New booking" : "Book a service"}
        </h1>
      </div>

      <ol className="flex flex-wrap items-center gap-2" aria-label="Progress">
        {steps.map((name, position) => (
          <li key={name} className="flex items-center gap-2">
            {position > 0 ? (
              <span aria-hidden className={cn("h-px w-6", position <= index ? "bg-accent-solid/50" : "bg-border")} />
            ) : null}
            <span
              aria-current={name === step ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 text-[13px]",
                name === step ? "font-medium text-foreground" : position < index ? "text-muted-foreground" : "text-muted-foreground/60",
              )}
            >
              <span
                className={cn(
                  "flex size-5 items-center justify-center rounded-full text-[11px] font-medium",
                  position < index && "bg-accent-solid text-accent-solid-foreground",
                  name === step && "border border-accent-solid text-accent-solid",
                  position > index && "border border-border text-muted-foreground/70",
                )}
              >
                {position < index ? <Check className="size-3" aria-hidden /> : position + 1}
              </span>
              {labels[name]}
            </span>
          </li>
        ))}
      </ol>

      {step === "customer" ? (
        <section aria-label="Choose a customer" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SearchInput
              value={customerQuery}
              onChange={setCustomerQuery}
              label="Search customers"
              placeholder="Name, email, phone or address"
            />
            <Button variant="outline" size="sm" render={<Link href="/customers?new=1" />}>
              Add a customer
            </Button>
          </div>
          {customers.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <CardSkeletons count={4} />
            </div>
          ) : null}
          {customers.isError ? (
            <Card>
              <ErrorState error={customers.error} onRetry={() => customers.refetch()} />
            </Card>
          ) : null}
          {customers.isSuccess && customers.data.data.length === 0 ? (
            <Card>
              <EmptyState
                icon={Users}
                title={customerQuery ? `No customers match “${customerQuery}”` : "No customers yet"}
                description="Add the customer first, then come back to book."
              />
            </Card>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            {(customers.data?.data ?? []).map((option) => (
              <Choice
                key={option.id}
                selected={chosenCustomer?.id === option.id}
                onSelect={() => {
                  setCustomer(option);
                  go("service");
                }}
              >
                <p className="truncate text-[14px] font-medium">{option.user.full_name}</p>
                <p className="truncate text-[12px] text-muted-foreground">{option.address ?? option.user.email}</p>
              </Choice>
            ))}
          </div>
        </section>
      ) : null}

      {step === "service" ? (
        <section aria-label="Choose a service" className="space-y-4">
          {staff && chosenCustomer ? (
            <p className="text-[13px] text-muted-foreground">
              For <span className="font-medium text-foreground">{chosenCustomer.user.full_name}</span>
              {chosenCustomer.address ? ` · ${chosenCustomer.address}` : ""}
            </p>
          ) : null}
          {services.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2">
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
              <EmptyState icon={Tags} title="No services available" description="This business hasn't published any bookable services yet." />
            </Card>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            {(services.data?.data ?? []).map((option) => (
              <Choice
                key={option.id}
                selected={service?.id === option.id}
                onSelect={() => {
                  setService(option);
                  setEmployeeId("");
                  go("time");
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[14px] font-medium">{option.name}</p>
                  <span className="shrink-0 text-[14px] font-medium tabular-nums">{formatPrice(option.base_price)}</span>
                </div>
                {option.description ? (
                  <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{option.description}</p>
                ) : null}
                <p className="mt-2 flex items-center gap-1.5 text-[12px] text-muted-foreground">
                  <Clock className="size-3.5" aria-hidden />
                  {formatDuration(option.duration_minutes)}
                </p>
              </Choice>
            ))}
          </div>
          {staff ? (
            <Button variant="outline" onClick={() => go("customer")}>
              Back
            </Button>
          ) : null}
        </section>
      ) : null}

      {step === "time" && service ? (
        <section aria-label="Choose a time and technician" className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <Card className="h-fit space-y-4 p-5">
            <div className="space-y-1.5">
              <Label htmlFor="booking-date">Date</Label>
              <Input
                id="booking-date"
                type="date"
                min={todayIn(timeZone)}
                value={date}
                onChange={(event) => {
                  setDate(event.target.value);
                  setEmployeeId("");
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="booking-time">Start time</Label>
              <FieldSelect
                id="booking-time"
                label="Start time"
                value={time === null ? "" : String(time)}
                onChange={(value) => {
                  setTime(value === "" ? null : Number(value));
                  setEmployeeId("");
                }}
                className="w-full"
              >
                <option value="">Choose a time</option>
                {TIMES.map((minutes) => (
                  <option key={minutes} value={minutes}>
                    {minutesToLabel(minutes)}
                  </option>
                ))}
              </FieldSelect>
              <p className="text-[12px] text-muted-foreground">
                {service.name} takes {formatDuration(service.duration_minutes)}. Times are in the business&apos;s local time (
                {timeZone.split("/").pop()?.replace("_", " ")}).
              </p>
              {inPast ? <p className="text-[13px] text-destructive">Choose a time that hasn&apos;t passed yet.</p> : null}
            </div>
          </Card>

          <Card className="space-y-3 p-5">
            <h2 className="text-[14px] font-medium">Technician</h2>
            {!startIso || inPast ? (
              <p className="text-[13px] text-muted-foreground">Choose a date and time to see who&apos;s available.</p>
            ) : null}
            {candidates.isFetching && !candidates.data ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : null}
            {candidates.isError ? <ErrorState error={candidates.error} onRetry={() => candidates.refetch()} /> : null}
            {candidates.data ? (
              <div className="divide-y overflow-hidden rounded-md border" role="radiogroup" aria-label="Technician">
                <label className={cn("flex cursor-pointer items-start gap-3 px-3 py-2.5 hover:bg-muted/50", employeeId === "" && "bg-accent-solid/[0.06]")}>
                  <input
                    type="radio"
                    name="technician"
                    className="mt-1 size-3.5 accent-[var(--accent-solid)]"
                    checked={employeeId === ""}
                    onChange={() => setEmployeeId("")}
                  />
                  <span>
                    <span className="block text-[13px] font-medium">{staff ? "Leave unassigned" : "No preference"}</span>
                    <span className="block text-[12px] text-muted-foreground">
                      {staff ? "It waits on the jobs board until someone is assigned." : "The team assigns the best available technician."}
                    </span>
                  </span>
                </label>
                {candidates.data.data.length === 0 ? (
                  <p className="px-3 py-3 text-[13px] text-muted-foreground">
                    {staff ? `Nobody is qualified for ${service.name} yet.` : "No technician is free at that time. Try another time, or leave it with no preference."}
                  </p>
                ) : null}
                {candidates.data.data.map((candidate) => (
                  <label
                    key={candidate.id}
                    className={cn(
                      "flex items-start gap-3 px-3 py-2.5",
                      candidate.assignable ? "cursor-pointer hover:bg-muted/50" : "cursor-not-allowed",
                      employeeId === candidate.id && "bg-accent-solid/[0.06]",
                    )}
                  >
                    <input
                      type="radio"
                      name="technician"
                      className="mt-1 size-3.5 accent-[var(--accent-solid)]"
                      checked={employeeId === candidate.id}
                      disabled={!candidate.assignable}
                      onChange={() => setEmployeeId(candidate.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-2">
                        <span className={cn("text-[13px] font-medium", !candidate.assignable && "text-muted-foreground")}>
                          {candidate.full_name}
                        </span>
                        <span className="text-[12px] text-muted-foreground">{candidate.job_title}</span>
                        {!candidate.assignable ? (
                          <span className="text-[11px] font-medium text-muted-foreground">{candidate.conflict ? "Booked" : "Not working"}</span>
                        ) : null}
                      </span>
                      {candidate.reason ? (
                        <span className="block text-[12px] text-muted-foreground">{candidate.reason}</span>
                      ) : staff ? (
                        <span className="block text-[12px] text-muted-foreground">
                          {candidate.jobs_today} {candidate.jobs_today === 1 ? "job" : "jobs"} that day
                        </span>
                      ) : null}
                    </span>
                  </label>
                ))}
              </div>
            ) : null}
            <div className="flex gap-2 pt-1">
              <Button variant="outline" onClick={() => go("service")}>
                Back
              </Button>
              <Button disabled={!startIso || inPast} onClick={() => go("review")}>
                Review
              </Button>
            </div>
          </Card>
        </section>
      ) : null}

      {step === "review" && service && startIso ? (
        <section aria-label="Review and confirm" className="space-y-4">
          {conflict ? (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-status-danger/30 bg-status-danger/[0.07] p-3.5">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-status-danger" aria-hidden />
              <div className="space-y-2">
                <p className="text-[13px] font-medium">{conflict}</p>
                <Button variant="outline" size="sm" onClick={() => go("time")}>
                  Choose another technician or time
                </Button>
              </div>
            </div>
          ) : null}

          <Card className="divide-y p-0">
            <dl className="grid gap-4 p-5 sm:grid-cols-2">
              {staff && chosenCustomer ? (
                <div>
                  <dt className="text-[12px] text-muted-foreground">Customer</dt>
                  <dd className="mt-1 text-[14px] font-medium">{chosenCustomer.user.full_name}</dd>
                  <dd className="text-[13px] text-muted-foreground">{chosenCustomer.address ?? "No address on file"}</dd>
                </div>
              ) : null}
              <div>
                <dt className="text-[12px] text-muted-foreground">Service</dt>
                <dd className="mt-1 text-[14px] font-medium">{service.name}</dd>
                <dd className="text-[13px] text-muted-foreground">
                  {formatPrice(service.base_price)} · {formatDuration(service.duration_minutes)}
                </dd>
              </div>
              <div>
                <dt className="text-[12px] text-muted-foreground">When</dt>
                <dd className="mt-1 text-[14px] font-medium">
                  {formatWindow(startIso, new Date(new Date(startIso).getTime() + service.duration_minutes * 60_000).toISOString(), timeZone)}
                </dd>
              </div>
              <div>
                <dt className="text-[12px] text-muted-foreground">Technician</dt>
                <dd className="mt-1 flex items-center gap-1.5 text-[14px] font-medium">
                  <UserRound className="size-4 text-muted-foreground" aria-hidden />
                  {technician ? technician.full_name : staff ? "Unassigned for now" : "No preference"}
                </dd>
              </div>
            </dl>
            <div className="space-y-2 p-5">
              <Label htmlFor="booking-notes">{staff ? "Notes for the technician (optional)" : "Anything we should know? (optional)"}</Label>
              <Textarea
                id="booking-notes"
                rows={3}
                maxLength={2000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                aria-describedby="booking-notes-help"
              />
              <p id="booking-notes-help" className="text-[12px] text-muted-foreground">
                For example: gate code, where the water heater is, pets at home.
              </p>
            </div>
          </Card>

          <p className="text-[13px] text-muted-foreground">
            {technician
              ? `${technician.full_name} is booked for this slot as soon as you confirm, at ${formatTime(startIso, timeZone)}.`
              : "It's saved without a technician and appears on the jobs board as needing one."}{" "}
            A confirmation email is sent after the booking is saved.
          </p>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => go("time")} disabled={submit.isPending}>
              Back
            </Button>
            <Button onClick={onSubmit} disabled={submit.isPending}>
              {submit.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              {submit.isPending ? "Booking..." : "Confirm booking"}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** 510 -> "08:30", for building a local date-time string. */
function minutesToLabelClock(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}
