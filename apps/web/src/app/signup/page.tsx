import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, CardContent } from "@/components/ui/card";
import { getSessionToken } from "@/lib/session";

import { SignupForm } from "./signup-form";

export const metadata = { title: "Create an account · ServiceFlow" };

/**
 * Single-tenant sign-up for the demo shop. A real multi-tenant deployment would
 * reach this page on the organization's own subdomain or slug route.
 */
const DEMO_ORGANIZATION_SLUG = "gleam-auto-detailing";

export default async function SignupPage() {
  if (await getSessionToken()) redirect("/dashboard");

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        <div className="space-y-2 text-center">
          <div className="mx-auto flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <span className="text-lg font-semibold">S</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
          <p className="text-sm text-muted-foreground">
            Book detailing with Gleam Auto Detailing.
          </p>
        </div>

        <Card>
          <CardContent className="pt-6">
            <SignupForm organizationSlug={DEMO_ORGANIZATION_SLUG} />
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-foreground hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
