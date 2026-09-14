"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Camera, MapPin, MessageSquare, User, Wrench } from "lucide-react";
import Link from "next/link";

import { BookingStatusBadge, JobStatusBadge } from "@/components/data/status-badge";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api-client";
import { formatDuration, formatPrice, formatRelative, formatWindow } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Booking, JobNote, JobPhoto } from "@/lib/types";

/**
 * One booking, for its customer or for staff. Photos and notes come from the
 * same endpoints either way; the API decides what each may see, so nothing is
 * filtered here - an INTERNAL note simply never arrives for a customer.
 */
export function BookingDetailClient({
  bookingId,
  timeZone,
  staff,
  canOpenJob,
}: {
  bookingId: string;
  timeZone: string;
  staff: boolean;
  canOpenJob: boolean;
}) {
  const booking = useQuery<{ data: Booking }, ApiError>({
    queryKey: queryKeys.bookings.detail(bookingId),
    queryFn: () => apiFetch<{ data: Booking }>(`bookings/${bookingId}`),
  });

  const jobId = booking.data?.data.job?.id;

  const photos = useQuery<{ data: JobPhoto[] }, ApiError>({
    queryKey: queryKeys.jobs.photos(jobId ?? "none"),
    queryFn: () => apiFetch<{ data: JobPhoto[] }>(`jobs/${jobId}/photos`),
    enabled: Boolean(jobId),
  });

  const notes = useQuery<{ data: JobNote[] }, ApiError>({
    queryKey: queryKeys.jobs.notes(jobId ?? "none"),
    queryFn: () => apiFetch<{ data: JobNote[] }>(`jobs/${jobId}/notes`),
    enabled: Boolean(jobId),
  });

  if (booking.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Card className="space-y-3 p-5">
          <Skeleton className="h-6 w-2/5" />
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-24 w-full" />
        </Card>
      </div>
    );
  }

  if (booking.isError || !booking.data) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/bookings" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back to bookings
        </Button>
        <Card>
          <ErrorState error={booking.error} onRetry={() => booking.refetch()} />
        </Card>
      </div>
    );
  }

  const row = booking.data.data;
  const photoRows = photos.data?.data ?? [];
  const noteRows = notes.data?.data ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" className="-ml-2" render={<Link href="/bookings" />}>
          <ArrowLeft className="size-4" aria-hidden />
          Back to bookings
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.015em]">{row.service.name}</h1>
          <BookingStatusBadge status={row.status} variant="chip" />
          {row.job ? <JobStatusBadge status={row.job.status} /> : null}
        </div>
        <p className="text-sm text-muted-foreground">
          {formatWindow(row.requested_start, row.requested_end, timeZone)} ·{" "}
          {formatDuration(row.service.duration_minutes)} · {formatPrice(row.service.base_price)}
        </p>
      </div>

      <Card className="space-y-4 p-5">
        <section className="grid gap-4 sm:grid-cols-2">
          {staff && row.customer ? (
            <div className="space-y-1">
              <h2 className="text-[12px] text-muted-foreground">Customer</h2>
              <p className="flex items-center gap-2 text-[14px] font-medium">
                <User className="size-4 text-muted-foreground" aria-hidden />
                <Link href={`/customers/${row.customer.id}`} className="focus-ring hover:underline">
                  {row.customer.full_name}
                </Link>
              </p>
              {row.customer.address ? (
                <p className="flex items-start gap-2 text-[13px] text-muted-foreground">
                  <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {row.customer.address}
                </p>
              ) : null}
            </div>
          ) : null}
          {row.job ? (
            <div className="space-y-1">
              <h2 className="text-[12px] text-muted-foreground">Technician</h2>
              <p className="flex items-center gap-2 text-[14px] font-medium">
                <Wrench className="size-4 text-muted-foreground" aria-hidden />
                {row.job.employee_name ?? "Not assigned yet"}
              </p>
              {canOpenJob ? (
                <Link href={`/jobs/${row.job.id}`} className="focus-ring text-[13px] text-accent-solid hover:underline">
                  Open job
                </Link>
              ) : null}
              {row.job.completed_at ? (
                <p className="text-sm text-muted-foreground">
                  Finished {formatRelative(row.job.completed_at)}
                </p>
              ) : null}
            </div>
          ) : null}
        </section>

        {row.customer_notes ? (
          <>
            <Separator />
            <section className="space-y-1.5">
              <h2 className="text-[12px] text-muted-foreground">
                {staff ? "Note from the customer" : "What you asked for"}
              </h2>
              <p className="whitespace-pre-wrap border-l-2 border-border pl-3 text-[13px]">
                {row.customer_notes}
              </p>
            </section>
          </>
        ) : null}
      </Card>

      {row.job ? (
        <>
          <Card className="space-y-4 p-5">
            <h2 className="font-medium">Photos from your visit</h2>

            {photos.isPending ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[0, 1, 2, 3].map((index) => (
                  <Skeleton key={index} className="aspect-square rounded-lg" />
                ))}
              </div>
            ) : null}

            {photos.isError ? (
              <ErrorState error={photos.error} onRetry={() => photos.refetch()} />
            ) : null}

            {photos.isSuccess && photoRows.length === 0 ? (
              <EmptyState
                icon={Camera}
                title="No photos yet"
                description="Your technician adds before and after shots as the work progresses."
              />
            ) : null}

            {(["BEFORE", "AFTER", "OTHER"] as const).map((kind) => {
              const inGroup = photoRows.filter((photo) => photo.photo_type === kind);
              if (inGroup.length === 0) return null;
              return (
                <section key={kind} className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {kind === "BEFORE" ? "Before" : kind === "AFTER" ? "After" : "Other"}
                  </h3>
                  <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                    {inGroup.map((photo) => (
                      <li key={photo.id}>
                        <a
                          href={photo.url}
                          target="_blank"
                          rel="noreferrer"
                          className="block overflow-hidden rounded-lg border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element -- presigned S3 URLs are not a configured next/image host */}
                          <img
                            src={photo.url}
                            alt={`${kind.toLowerCase()} photo from the ${row.service.name} visit`}
                            loading="lazy"
                            className="aspect-square w-full bg-muted object-cover"
                          />
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </Card>

          <Card className="space-y-4 p-5">
            <h2 className="font-medium">Notes from the team</h2>

            {notes.isPending ? (
              <div className="space-y-2">
                {[0, 1].map((index) => (
                  <Skeleton key={index} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            ) : null}

            {notes.isError ? (
              <ErrorState error={notes.error} onRetry={() => notes.refetch()} />
            ) : null}

            {notes.isSuccess && noteRows.length === 0 ? (
              <EmptyState
                icon={MessageSquare}
                title="No notes yet"
                description="Anything the team wants to share about your visit will appear here."
              />
            ) : null}

            <ul className="space-y-3">
              {noteRows.map((note) => (
                <li key={note.id} className="rounded-lg border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{note.author_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatRelative(note.created_at)}
                    </span>
                  </div>
                  <p className="mt-1.5 whitespace-pre-wrap text-sm">{note.content}</p>
                </li>
              ))}
            </ul>
          </Card>
        </>
      ) : (
        <Card>
          <EmptyState
            icon={Camera}
            title="Nothing to show yet"
            description="Photos and notes from the visit appear here once the work begins."
          />
        </Card>
      )}

    </div>
  );
}
