import { CalendarCheck2, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getSessionToken } from "@/lib/session";

import { DemoAccounts } from "./demo-accounts";
import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in · ServiceFlow" };

const POINTS = [
  { icon: CalendarCheck2, text: "Bookings that can't double-book a technician" },
  { icon: Users, text: "Seven roles, from dispatcher to customer" },
  { icon: ShieldCheck, text: "Every business's data kept to itself" },
];

export default async function LoginPage() {
  if (await getSessionToken()) redirect("/dashboard");

  return (
    <main className="grid min-h-svh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      {/* A quiet panel that says what the product is, once. No hero, no gradient. */}
      <section className="hidden flex-col justify-between border-r bg-sidebar px-12 py-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <span className="text-[14px] font-semibold">S</span>
          </div>
          <span className="text-[15px] font-semibold tracking-[-0.01em]">ServiceFlow</span>
        </div>
        <div className="max-w-md space-y-6">
          <h2 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">
            Scheduling, dispatch and job tracking for service businesses.
          </h2>
          <ul className="space-y-3">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-[14px] text-muted-foreground">
                <Icon className="size-4 shrink-0 text-accent-solid" aria-hidden />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-[12px] text-muted-foreground">Portfolio project · local demo environment</p>
      </section>

      <section className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px] space-y-6">
          <div className="space-y-1.5">
            <div className="mb-4 flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground lg:hidden">
              <span className="text-[15px] font-semibold">S</span>
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-0.015em]">Sign in to ServiceFlow</h1>
            <p className="text-[14px] text-muted-foreground">Use your work email, or pick a demo role below.</p>
          </div>

          <div className="space-y-5 rounded-lg border bg-surface p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <LoginForm />
            <DemoAccounts />
          </div>

          <p className="text-center text-[13px] text-muted-foreground">
            New customer of Northside Home Services?{" "}
            <Link href="/signup" className="font-medium text-foreground hover:underline">
              Create an account
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
