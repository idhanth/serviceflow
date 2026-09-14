"use client";

import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A compact filter select.
 *
 * A native <select> for the behaviour - keyboard, mobile pickers and typeahead
 * come free - with the browser's chrome removed so it sits at the same height
 * and weight as the buttons beside it. A styled listbox would look identical
 * and behave worse.
 */
export function FieldSelect({
  id,
  label,
  value,
  onChange,
  children,
  className,
}: {
  /** Set when a visible <Label htmlFor> names the select; aria-label is used otherwise. */
  id?: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <select
        id={id}
        aria-label={id ? undefined : label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          "focus-ring h-8 w-full appearance-none rounded-md border bg-surface pl-2.5 pr-7",
          "text-[13px] text-foreground transition-colors duration-75 hover:bg-muted/50",
        )}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  );
}
