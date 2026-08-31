"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api-client";

/** One-click demo logins (PRD 50) so the app can be explored immediately. */
const DEMO_ACCOUNTS = [
  { label: "Admin", email: "admin@serviceflow.demo" },
  { label: "Employee", email: "employee@serviceflow.demo" },
  { label: "Customer", email: "customer@serviceflow.demo" },
] as const;

const DEMO_PASSWORD = "demo1234";

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
      toast.error(
        error instanceof ApiError ? error.message : "Couldn't start the demo session.",
      );
      setPending(null);
    }
  }

  return (
    // Part of the sign-in card, separated by a rule: a second bordered box
    // below the first made the page look like two unrelated forms.
    <div className="space-y-2.5 border-t pt-4">
      <p className="text-[12px] text-muted-foreground">Or explore with a demo account</p>
      <div className="grid grid-cols-3 gap-2">
        {DEMO_ACCOUNTS.map((account) => (
          <Button
            key={account.email}
            variant="outline"
            size="sm"
            disabled={pending !== null}
            onClick={() => signInAs(account.email)}
          >
            {pending === account.email ? "..." : account.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
