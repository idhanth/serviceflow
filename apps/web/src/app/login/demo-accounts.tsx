"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { apiFetch, ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * One-click sign-in for each role, so the product can be explored immediately.
 *
 * These accounts exist only in the seeded local demo database. The password is
 * public on purpose and is never valid anywhere else.
 */
const DEMO_ACCOUNTS = [
  { role: "Business Owner", person: "Dana Whitfield", email: "owner@serviceflow.demo" },
  { role: "Dispatcher", person: "Priya Shah", email: "dispatcher@serviceflow.demo" },
  { role: "Technician", person: "Alex Morgan", email: "employee@serviceflow.demo" },
  { role: "Customer", person: "Sarah Mitchell", email: "customer@serviceflow.demo" },
  { role: "Manager", person: "Marcus Hale", email: "manager@serviceflow.demo" },
  { role: "Analyst", person: "Read-only", email: "analyst@serviceflow.demo" },
  { role: "Platform Admin", person: "All businesses", email: "admin@serviceflow.demo" },
] as const;

export const DEMO_PASSWORD = "demo1234";

export function DemoAccounts() {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);

  async function signInAs(email: string) {
    setPending(email);
    try {
      await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password: DEMO_PASSWORD }),
      });
      router.replace("/dashboard");
      router.refresh();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Couldn't start the demo session.");
      setPending(null);
    }
  }

  return (
    <section aria-labelledby="demo-heading" className="space-y-3 border-t pt-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="demo-heading" className="text-[13px] font-medium">
          Explore as
        </h2>
        <p className="text-[12px] text-muted-foreground">
          Demo accounts · password <code className="font-mono">{DEMO_PASSWORD}</code>
        </p>
      </div>
      <ul className="grid grid-cols-2 gap-2">
        {DEMO_ACCOUNTS.map((account) => (
          <li key={account.email} className={cn(account.role === "Platform Admin" && "col-span-2")}>
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => signInAs(account.email)}
              aria-label={`Sign in as the demo ${account.role}`}
              className={cn(
                "focus-ring flex w-full items-center justify-between gap-2 rounded-md border bg-surface px-3 py-2 text-left",
                "transition-colors duration-75 hover:border-accent-solid/40 hover:bg-muted/40",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
            >
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium">{account.role}</span>
                <span className="block truncate text-[12px] text-muted-foreground">{account.person}</span>
              </span>
              {pending === account.email ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
              ) : null}
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[12px] leading-relaxed text-muted-foreground">
        Local demo data only. Every account belongs to Northside Home Services except the platform
        admin, who sees the businesses on the platform but none of their records.
      </p>
    </section>
  );
}
