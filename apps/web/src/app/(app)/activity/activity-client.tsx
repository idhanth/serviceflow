"use client";

import { History } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/data/page-header";
import { PaginationControls } from "@/components/data/pagination-controls";
import { EmptyState, ErrorState, TableSkeletonRows } from "@/components/data/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";

import { usePagedResource } from "@/hooks/use-resource";
import { apiFetchData } from "@/lib/api-client";
import { formatDate, formatRelative, initialsOf } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { AuditActor, AuditEntry } from "@/lib/types";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const COLUMNS = 4;

/** Broad groups, so an admin can ask "what happened to bookings" in one click. */
const AREAS = [
  { label: "Everything", value: "all", resourceType: undefined },
  { label: "Bookings", value: "booking", resourceType: "booking" },
  { label: "Jobs", value: "job", resourceType: "job" },
  { label: "Team", value: "employee", resourceType: "employee" },
  { label: "Catalog", value: "service", resourceType: "service" },
] as const;

const PERIODS = [
  { label: "24 hours", value: "1", days: 1 },
  { label: "7 days", value: "7", days: 7 },
  { label: "30 days", value: "30", days: 30 },
  { label: "All time", value: "all", days: null },
] as const;

type Area = (typeof AREAS)[number]["value"];
type Period = (typeof PERIODS)[number]["value"];

/** "BOOKING_RESCHEDULED" reads badly in a table; this is the same thing in English. */
function describeAction(action: string): string {
  const words = action.toLowerCase().split("_");
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

function toneOf(action: string): "default" | "secondary" | "destructive" | "outline" {
  if (action.endsWith("CANCELLED") || action.endsWith("REJECTED") || action.endsWith("DELETED")) {
    return "destructive";
  }
  if (action.endsWith("CREATED") || action.endsWith("COMPLETED")) return "default";
  return "secondary";
}

/** The metadata is a small, already-redacted summary; render it as plain facts. */
function summarize(entry: AuditEntry): string | null {
  if (!entry.metadata) return null;
  const parts = Object.entries(entry.metadata)
    .filter(([, value]) => value !== null && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`);
  return parts.length ? parts.join(" · ") : null;
}

/** The oldest timestamp a period includes, or undefined for all time. */
function boundaryFor(period: Period): string | undefined {
  const days = PERIODS.find((option) => option.value === period)?.days ?? null;
  return days ? new Date(Date.now() - days * 86_400_000).toISOString() : undefined;
}

export function ActivityClient() {
  const [area, setArea] = useState<Area>("all");
  const [period, setPeriod] = useState<Period>("7");
  // Held in state, not derived during render: a boundary recomputed every render
  // would change the query key every render, and the feed would never settle.
  const [since, setSince] = useState<string | undefined>(() => boundaryFor("7"));
  const [actorId, setActorId] = useState("all");
  const [page, setPage] = useState(1);

  const params = {
    page,
    page_size: 20,
    resource_type: AREAS.find((option) => option.value === area)?.resourceType,
    actor_user_id: actorId === "all" ? undefined : actorId,
    since,
  };

  const query = usePagedResource<AuditEntry>(queryKeys.activity.list(params), "activity", params);
  const actors = useQuery<AuditActor[]>({
    queryKey: queryKeys.activity.actors,
    queryFn: () => apiFetchData<AuditActor[]>("activity/actors"),
  });

  function reset<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setPage(1);
    };
  }

  const entries = query.data?.data ?? [];
  const showEmpty = query.isSuccess && entries.length === 0;
  const filtered = area !== "all" || period !== "7" || actorId !== "all";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Activity"
        description="Who changed what, and when. Entries are permanent and cannot be edited."
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div role="group" aria-label="Filter by area" className="flex flex-wrap rounded-lg border p-0.5">
          {AREAS.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={area === option.value ? "secondary" : "ghost"}
              aria-pressed={area === option.value}
              onClick={() => reset(setArea)(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Select
            value={actorId}
            onValueChange={(value) => reset(setActorId)(String(value))}
            items={[
              { label: "Anyone", value: "all" },
              ...(actors.data ?? []).map((actor) => ({
                label: actor.full_name,
                value: actor.id,
              })),
            ]}
          >
            <SelectTrigger aria-label="Filter by person" className="min-w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Anyone</SelectItem>
              {(actors.data ?? []).map((actor) => (
                <SelectItem key={actor.id} value={actor.id}>
                  {actor.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div role="group" aria-label="Filter by period" className="flex rounded-lg border p-0.5">
            {PERIODS.map((option) => (
              <Button
                key={option.value}
                type="button"
                size="sm"
                variant={period === option.value ? "secondary" : "ghost"}
                aria-pressed={period === option.value}
                onClick={() => {
                  setPeriod(option.value);
                  setSince(boundaryFor(option.value));
                  setPage(1);
                }}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[200px]">Who</TableHead>
                <TableHead className="min-w-[180px]">Did what</TableHead>
                <TableHead className="min-w-[260px]">Details</TableHead>
                <TableHead className="min-w-[160px]">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.isPending ? <TableSkeletonRows columns={COLUMNS} /> : null}

              {query.isError ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <ErrorState error={query.error} onRetry={() => query.refetch()} />
                  </TableCell>
                </TableRow>
              ) : null}

              {showEmpty ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS} className="p-0">
                    <EmptyState
                      icon={History}
                      title={filtered ? "Nothing in this range" : "No activity yet"}
                      description={
                        filtered
                          ? "Try a wider period, or a different area."
                          : "Once your team starts confirming and working on bookings, the trail appears here."
                      }
                      action={
                        filtered ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setArea("all");
                              setPeriod("all");
                              setSince(undefined);
                              setActorId("all");
                              setPage(1);
                            }}
                          >
                            Clear filters
                          </Button>
                        ) : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              ) : null}

              {entries.map((entry) => {
                const detail = summarize(entry);
                return (
                  <TableRow key={entry.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar className="size-8">
                          <AvatarFallback className="text-xs">
                            {initialsOf(entry.actor_name)}
                          </AvatarFallback>
                        </Avatar>
                        <span className="truncate font-medium">{entry.actor_name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={toneOf(entry.action)} className="font-normal">
                        {describeAction(entry.action)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      <span className="capitalize">{entry.resource_type}</span>
                      {detail ? <span> — {detail}</span> : null}
                    </TableCell>
                    <TableCell className="text-sm">
                      <div>{formatRelative(entry.created_at)}</div>
                      <div className="text-muted-foreground">{formatDate(entry.created_at)}</div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </Card>

      {query.data ? (
        <PaginationControls meta={query.data.meta} onPageChange={setPage} noun="entries" />
      ) : null}
    </div>
  );
}
