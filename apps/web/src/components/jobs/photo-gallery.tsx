"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Camera, RotateCw, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch, ApiError } from "@/lib/api-client";
import { formatBytes } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { JobPhoto, PhotoType } from "@/lib/types";
import {
  MAX_PHOTOS_PER_JOB,
  ALLOWED_IMAGE_TYPES,
  describeRejection,
  uploadJobPhoto,
} from "@/lib/upload";
import { cn } from "@/lib/utils";

const GROUPS: { type: PhotoType; label: string }[] = [
  { type: "BEFORE", label: "Before" },
  { type: "AFTER", label: "After" },
  { type: "OTHER", label: "Other" },
];

interface Pending {
  id: string;
  file: File;
  photoType: PhotoType;
  percent: number;
  error: string | null;
}

export function PhotoGallery({
  jobId,
  canEdit,
  canDelete,
}: {
  jobId: string;
  canEdit: boolean;
  canDelete: boolean;
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [photoType, setPhotoType] = useState<PhotoType>("BEFORE");
  const [pending, setPending] = useState<Pending[]>([]);
  const [dragging, setDragging] = useState(false);
  const [removing, setRemoving] = useState<JobPhoto | null>(null);
  const [deleting, setDeleting] = useState(false);

  const query = useQuery<{ data: JobPhoto[] }, ApiError>({
    queryKey: queryKeys.jobs.photos(jobId),
    queryFn: () => apiFetch<{ data: JobPhoto[] }>(`jobs/${jobId}/photos`),
  });

  const photos = query.data?.data ?? [];
  const remaining = MAX_PHOTOS_PER_JOB - photos.length - pending.length;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.photos(jobId) });
  }

  async function runUpload(entry: Pending) {
    setPending((current) =>
      current.map((item) => (item.id === entry.id ? { ...item, error: null, percent: 0 } : item)),
    );
    try {
      await uploadJobPhoto({
        jobId,
        file: entry.file,
        photoType: entry.photoType,
        onProgress: (percent) =>
          setPending((current) =>
            current.map((item) => (item.id === entry.id ? { ...item, percent } : item)),
          ),
      });
      setPending((current) => current.filter((item) => item.id !== entry.id));
      refresh();
      toast.success(`${entry.file.name} uploaded`);
    } catch (error) {
      // Kept in the list with a Retry button rather than silently dropped.
      const message =
        error instanceof ApiError ? error.message : "The upload failed. Try again.";
      setPending((current) =>
        current.map((item) => (item.id === entry.id ? { ...item, error: message } : item)),
      );
    }
  }

  function accept(files: FileList | null) {
    if (!files || files.length === 0) return;
    const queued: Pending[] = [];

    for (const file of Array.from(files)) {
      if (queued.length >= remaining) {
        toast.error(`This job can hold at most ${MAX_PHOTOS_PER_JOB} photos.`);
        break;
      }
      const rejection = describeRejection(file);
      if (rejection) {
        toast.error(rejection);
        continue;
      }
      queued.push({
        id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        photoType,
        percent: 0,
        error: null,
      });
    }

    if (queued.length === 0) return;
    setPending((current) => [...current, ...queued]);
    for (const entry of queued) void runUpload(entry);
  }

  async function confirmRemove() {
    if (!removing) return;
    setDeleting(true);
    try {
      await apiFetch(`jobs/${jobId}/photos/${removing.id}`, { method: "DELETE" });
      refresh();
      toast.success("Photo removed");
      setRemoving(null);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Couldn't remove that photo.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">Photos</h2>
          <p className="text-sm text-muted-foreground">
            {photos.length} of {MAX_PHOTOS_PER_JOB} · JPEG, PNG or WebP up to 10 MB
          </p>
        </div>
      </div>

      {canEdit ? (
        <div className="space-y-3">
          <fieldset className="flex flex-wrap items-center gap-2">
            <legend className="sr-only">Photo type</legend>
            <span className="text-sm text-muted-foreground">Upload as</span>
            <div className="flex rounded-lg border p-0.5">
              {GROUPS.map((group) => (
                <Button
                  key={group.type}
                  type="button"
                  size="sm"
                  variant={photoType === group.type ? "secondary" : "ghost"}
                  aria-pressed={photoType === group.type}
                  onClick={() => setPhotoType(group.type)}
                >
                  {group.label}
                </Button>
              ))}
            </div>
          </fieldset>

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (remaining > 0) accept(event.dataTransfer.files);
            }}
            className={cn(
              "rounded-lg border border-dashed p-5 text-center transition-colors duration-150",
              dragging ? "border-primary bg-primary/5" : "border-muted-foreground/25",
              remaining <= 0 && "opacity-60",
            )}
          >
            <Upload className="mx-auto size-6 text-muted-foreground" aria-hidden />
            <p className="mt-2 text-sm">
              Drag photos here, or{" "}
              <button
                type="button"
                className="font-medium underline underline-offset-2 disabled:no-underline"
                disabled={remaining <= 0}
                onClick={() => inputRef.current?.click()}
              >
                choose files
              </button>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {remaining > 0
                ? `${remaining} slot${remaining === 1 ? "" : "s"} left`
                : "This job is at the photo limit"}
            </p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ALLOWED_IMAGE_TYPES.join(",")}
              className="sr-only"
              aria-label="Choose photos to upload"
              onChange={(event) => {
                accept(event.target.files);
                event.target.value = "";
              }}
            />
          </div>
        </div>
      ) : null}

      {pending.length > 0 ? (
        <ul className="space-y-2" aria-label="Uploads in progress">
          {pending.map((entry) => (
            <li key={entry.id} className="rounded-lg border p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate text-sm">{entry.file.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatBytes(entry.file.size)}
                </span>
              </div>

              {entry.error ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-1.5 text-sm text-destructive">
                    <AlertCircle className="size-3.5" aria-hidden />
                    {entry.error}
                  </span>
                  <Button size="sm" variant="outline" onClick={() => void runUpload(entry)}>
                    <RotateCw className="size-3.5" aria-hidden />
                    Retry
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setPending((current) => current.filter((item) => item.id !== entry.id))
                    }
                  >
                    <X className="size-3.5" aria-hidden />
                    Discard
                  </Button>
                </div>
              ) : (
                <div className="mt-2 flex items-center gap-2">
                  <div
                    className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-valuenow={entry.percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`Uploading ${entry.file.name}`}
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-200"
                      style={{ width: `${entry.percent}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                    {entry.percent}%
                  </span>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {query.isPending ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="aspect-square rounded-md" />
          ))}
        </div>
      ) : null}

      {query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}

      {query.isSuccess && photos.length === 0 && pending.length === 0 ? (
        <EmptyState
          icon={Camera}
          title="No photos yet"
          description={
            canEdit
              ? "Before and after shots are the record of the work done."
              : "Photos will appear here once the work is under way."
          }
        />
      ) : null}

      {GROUPS.map((group) => {
        const inGroup = photos.filter((photo) => photo.photo_type === group.type);
        if (inGroup.length === 0) return null;
        return (
          <section key={group.type} className="space-y-2">
            <h3 className="text-[12px] font-medium text-muted-foreground">
              {group.label} ({inGroup.length})
            </h3>
            <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
              {inGroup.map((photo) => (
                <li key={photo.id} className="group relative">
                  <a
                    href={photo.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded-lg border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- presigned S3 URLs are not a configured next/image host */}
                    <img
                      src={photo.url}
                      alt={`${group.label} photo by ${photo.uploaded_by_name}`}
                      loading="lazy"
                      className="aspect-square w-full bg-muted object-cover"
                    />
                  </a>
                  {canDelete ? (
                    <Button
                      variant="secondary"
                      size="icon"
                      aria-label={`Remove ${group.label.toLowerCase()} photo`}
                      className="absolute right-1.5 top-1.5 size-7 opacity-0 shadow transition-opacity duration-150 group-hover:opacity-100 focus-visible:opacity-100"
                      onClick={() => setRemoving(photo)}
                    >
                      <Trash2 className="size-3.5 text-destructive" aria-hidden />
                    </Button>
                  ) : null}
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {formatBytes(photo.file_size)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this photo?"
        description="The image is deleted from storage as well as from this job. This cannot be undone."
        confirmLabel={deleting ? "Removing..." : "Remove photo"}
        pendingLabel="Removing..."
        onConfirm={confirmRemove}
      />
    </Card>
  );
}
