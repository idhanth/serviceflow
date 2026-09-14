"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Loader2, Search, Tags, User, Users, Wrench } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { apiFetch, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { SearchResult } from "@/lib/types";

const ICONS = {
  customer: Users,
  booking: ClipboardList,
  job: Wrench,
  employee: User,
  service: Tags,
} as const;

const LABELS = {
  customer: "Customer",
  booking: "Booking",
  job: "Job",
  employee: "Employee",
  service: "Service",
} as const;

/** Staff lookup across records, opened by click or Cmd/Ctrl+K. */
export function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term), 250);
    return () => clearTimeout(timer);
  }, [term]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const query = useQuery<{ data: SearchResult[] }, ApiError>({
    queryKey: queryKeys.search.query(debounced),
    queryFn: () =>
      apiFetch<{ data: SearchResult[] }>(`search?q=${encodeURIComponent(debounced)}`),
    enabled: open && debounced.trim().length >= 2,
  });

  const results = query.data?.data ?? [];

  function go(result: SearchResult) {
    setOpen(false);
    setTerm("");
    router.push(result.href);
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="w-full justify-start gap-2 text-muted-foreground"
        onClick={() => setOpen(true)}
      >
        <Search className="size-4" aria-hidden />
        <span className="flex-1 text-left">Search...</span>
        <kbd className="hidden rounded border px-1.5 text-[10px] sm:inline">⌘K</kbd>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="top-24 max-h-[70svh] translate-y-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="sr-only">
            <DialogTitle>Search</DialogTitle>
            <DialogDescription>
              Find customers, bookings, jobs, employees and services.
            </DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-2 border-b px-3">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <Input
              autoFocus
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Customers, addresses, bookings, jobs..."
              aria-label="Search everything"
              className="border-0 shadow-none focus-visible:ring-0"
            />
            {query.isFetching ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
            ) : null}
          </div>

          <div className="max-h-[50svh] overflow-y-auto p-2">
            {term.trim().length < 2 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                Type at least two characters.
              </p>
            ) : null}

            {query.isError ? (
              <p className="px-2 py-6 text-center text-sm text-destructive">
                {query.error.message}
              </p>
            ) : null}

            {query.isSuccess && results.length === 0 && debounced.trim().length >= 2 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                Nothing matched “{debounced}”.
              </p>
            ) : null}

            <ul>
              {results.map((result) => {
                const Icon = ICONS[result.kind];
                return (
                  <li key={`${result.kind}-${result.id}`}>
                    <button
                      type="button"
                      onClick={() => go(result)}
                      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:bg-accent"
                    >
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <Icon className="size-4 text-muted-foreground" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{result.title}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {result.subtitle}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {LABELS[result.kind]}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
