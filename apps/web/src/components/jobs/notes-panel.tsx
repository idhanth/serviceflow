"use client";

import { useQuery } from "@tanstack/react-query";
import { EyeOff, Loader2, MessageSquare, Send, Trash2, Users } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useResourceMutation } from "@/hooks/use-resource";
import { apiFetch, ApiError, apiFetchData } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { JobNote, NoteVisibility } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_LENGTH = 4000;

export function NotesPanel({
  jobId,
  canWrite,
  canDelete,
}: {
  jobId: string;
  canWrite: boolean;
  canDelete: boolean;
}) {
  const [content, setContent] = useState("");
  const [visibility, setVisibility] = useState<NoteVisibility>("INTERNAL");
  const [removing, setRemoving] = useState<JobNote | null>(null);

  const query = useQuery<{ data: JobNote[] }, ApiError>({
    queryKey: queryKeys.jobs.notes(jobId),
    queryFn: () => apiFetch<{ data: JobNote[] }>(`jobs/${jobId}/notes`),
  });

  const create = useResourceMutation<void, JobNote>(
    () =>
      apiFetchData<JobNote>(`jobs/${jobId}/notes`, {
        method: "POST",
        body: JSON.stringify({ content: content.trim(), visibility }),
      }),
    {
      invalidate: [queryKeys.jobs.notes(jobId)],
      successMessage: (note) =>
        note.visibility === "CUSTOMER_VISIBLE" ? "Note added for the customer" : "Internal note added",
    },
  );

  const remove = useResourceMutation<JobNote, null>(
    async (note) => {
      await apiFetch(`jobs/${jobId}/notes/${note.id}`, { method: "DELETE" });
      return null;
    },
    { invalidate: [queryKeys.jobs.notes(jobId)], successMessage: "Note removed" },
  );

  async function submit() {
    if (!content.trim() || create.isPending) return;
    try {
      await create.mutateAsync();
      setContent("");
    } catch {
      // The hook surfaced the server's message; the draft is kept for a retry.
    }
  }

  const notes = query.data?.data ?? [];

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="font-medium">Notes</h2>
        <p className="text-sm text-muted-foreground">
          {canWrite
            ? "Internal notes stay with the team. Customer-visible notes appear on their booking."
            : "Notes shared with you about this visit."}
        </p>
      </div>

      {canWrite ? (
        <div className="space-y-3 rounded-lg border p-3">
          <div className="space-y-2">
            <Label htmlFor="note-content">New note</Label>
            <Textarea
              id="note-content"
              rows={3}
              maxLength={MAX_LENGTH}
              value={content}
              disabled={create.isPending}
              placeholder="What happened, or what the customer should know."
              onChange={(event) => setContent(event.target.value)}
            />
            <p className="text-right text-xs text-muted-foreground">
              {content.length}/{MAX_LENGTH}
            </p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Who can see this?</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  {
                    value: "INTERNAL" as const,
                    label: "Team only",
                    hint: "The customer never sees it",
                    icon: EyeOff,
                  },
                  {
                    value: "CUSTOMER_VISIBLE" as const,
                    label: "Share with customer",
                    hint: "Shown on their booking",
                    icon: Users,
                  },
                ]
              ).map((option) => {
                const Icon = option.icon;
                return (
                  <label
                    key={option.value}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm transition-colors duration-150 hover:bg-accent/50",
                      visibility === option.value && "border-primary/50 bg-primary/5",
                    )}
                  >
                    <input
                      type="radio"
                      name="note-visibility"
                      className="mt-0.5 size-4 accent-primary"
                      checked={visibility === option.value}
                      disabled={create.isPending}
                      onChange={() => setVisibility(option.value)}
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 font-medium">
                        <Icon className="size-3.5" aria-hidden />
                        {option.label}
                      </span>
                      <span className="block text-xs text-muted-foreground">{option.hint}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <Button onClick={submit} disabled={!content.trim() || create.isPending}>
            {create.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Saving...
              </>
            ) : (
              <>
                <Send className="size-4" aria-hidden />
                Add note
              </>
            )}
          </Button>
        </div>
      ) : null}

      {query.isPending ? (
        <div className="space-y-2">
          {[0, 1].map((index) => (
            <Skeleton key={index} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      ) : null}

      {query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}

      {query.isSuccess && notes.length === 0 ? (
        <EmptyState
          icon={MessageSquare}
          title="No notes yet"
          description={
            canWrite
              ? "Record anything worth remembering about this job."
              : "Anything the team shares about this visit will appear here."
          }
        />
      ) : null}

      <ul className="space-y-3">
        {notes.map((note) => (
          <li key={note.id} className="rounded-lg border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{note.author_name}</span>
                {note.visibility === "INTERNAL" ? (
                  <Badge variant="outline" className="gap-1 bg-muted text-muted-foreground">
                    <EyeOff className="size-3" aria-hidden />
                    Team only
                  </Badge>
                ) : (
                  <Badge
                    variant="outline"
                    className="gap-1 border-blue-600/30 bg-blue-500/10 text-blue-700 dark:border-blue-400/30 dark:text-blue-300"
                  >
                    <Users className="size-3" aria-hidden />
                    Shared with customer
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1">
                <span className="text-xs text-muted-foreground">
                  {formatRelative(note.created_at)}
                </span>
                {canDelete ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label="Remove note"
                    onClick={() => setRemoving(note)}
                  >
                    <Trash2 className="size-3.5 text-destructive" aria-hidden />
                  </Button>
                ) : null}
              </div>
            </div>
            <p className="mt-1.5 whitespace-pre-wrap text-sm">{note.content}</p>
          </li>
        ))}
      </ul>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this note?"
        description="It will be deleted from the job's history. This cannot be undone."
        confirmLabel="Remove note"
        pendingLabel="Removing..."
        onConfirm={async () => {
          if (removing) await remove.mutateAsync(removing);
        }}
      />
    </Card>
  );
}
